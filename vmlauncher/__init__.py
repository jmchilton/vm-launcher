import os
import time

from libcloud.compute.ssh import SSHClient
from libcloud.compute.types import NodeState
from libcloud.compute.base import NodeImage, NodeSize
from libcloud.compute.types import Provider
from libcloud.compute.providers import get_driver

# Ubuntu 10.04 LTS (Lucid Lynx) Daily Build [20120302]
DEFAULT_AWS_IMAGE_ID = "ami-0bf6af4e"
DEFAULT_AWS_SIZE_ID = "m1.large"
DEFAULT_AWS_AVAILABILITY_ZONE = "us-west-1"

from fabric.api import local, env, sudo, put


class VmLauncher:

    def __init__(self, options):
        self.options = options
        self.__set_and_verify_key()

    def __set_and_verify_key(self):
        self.key_file = self.options['key_file']
        if not os.path.exists(self.key_file):
            raise Exception("Invalid or unspecified key_file options: %s" % self.key_file)

    def get_key_file(self):
        return self.key_file

    def boot_and_connect(self):
        conn = self.connect_driver()
        node = self._boot()  # Subclasses should implement this, and return libcloud node like object
        self.conn = conn
        self.node = node
        self.uuid = node.uuid
        self.connect(conn)

    def _wait_for_node_info(self, f):
        initial_value = f(self.node)
        if initial_value:
            return initial_value
        while True:
            time.sleep(10)
            refreshed_node = self._find_node()
            refreshed_value = f(refreshed_node)
            if refreshed_value:
                return refreshed_value

    def _find_node(self):
        nodes = self.conn.list_nodes()
        node_uuid = self.node.uuid
        for node in nodes:
            if node.uuid == node_uuid:
                return node

    def destroy(self, node=None):
        self.connect_driver()
        if node == None:
            node = self.node
        self.conn.destroy_node(node)

    def __get_ssh_client(self):
        ip = self.get_ip()  # Subclasses should implement this
        key_file = self.get_key_file()
        print "Creating ssh client connection to ip %s" % ip
        ssh_client = SSHClient(hostname=ip,
                               port=self.get_ssh_port(),
                               username=self.get_user(),
                               key=key_file)
        return ssh_client

    def get_user(self):
        return "ubuntu"

    def get_ssh_port(self):
        return 22

    def connect(self, conn, tries=5):
        i = 0
        while i < tries:
            try:
                ssh_client = self.__get_ssh_client()
                conn._ssh_client_connect(ssh_client=ssh_client, timeout=60)
                return
            except:
                i = i + 1

    def list(self):
        self.connect_driver()
        return self.conn.list_nodes()


class VagrantConnection:
    """'Fake' connection type to mimic libcloud's but for Vagrant"""

    def _ssh_client_connect(self, ssh_client):
        pass

    def destroy_node(self, node=None):
        local("vagrant halt")

    def list_nodes(self):
        return [VagrantNode()]


class VagrantNode:

    def __init__(self):
        self.name = "vagrant"
        self.uuid = "vagrant"


class VagrantVmLauncher(VmLauncher):
    """Launches vagrant VMs."""

    def connect_driver(self):
        self.conn = VagrantConnection()
        return self.conn

    def __init__(self, options):
        VmLauncher.__init__(self, options)
        self.uuid = "test"

    def _boot(self):
        local("vagrant up")
        return VagrantNode()

    def get_ip(self):
        return "33.33.33.11"

    def get_user(self):
        return "vagrant"

    def package(self):
        local("vagrant package")


class OpenstackVmLauncher(VmLauncher):
    """ Wrapper around libcloud's openstack API. """

    def __init__(self, options):
        VmLauncher.__init__(self, options)

    def get_ip(self):
        return self.public_ip

    def connect_driver(self):
        self.conn = self.__get_connection()
        return self.conn

    def _boot(self):
        conn = self.conn
        if 'use_existing_instance' in self.options['openstack']:
            instance_id = self.options['openstack']['use_existing_instance']
            nodes = conn.list_nodes()
            node = [node for node in nodes if node.uuid == instance_id][0]
            if not node:
                raise Exception("Failed to find instance of uuid %s" % instance_id)
        else:
            node = self.__boot_new(conn)
        return node

    def __boot_new(self, conn):
        if 'image_id' in self.options['openstack']:
            image_id = self.options['openstack']['image_id']
        else:
            image_id = None
        if self.options['openstack']:
            flavor_id = self.options['openstack']['flavor_id']
        else:
            flavor_id = None
        key_name = self.options['openstack']['keypair_name']
        hostname = self.options['hostname']
        self.public_ip = self.options['openstack']['public_ip']

        images = conn.list_images()
        image = [image for image in images if (not image_id) or (image.id == image_id)][0]
        sizes = conn.list_sizes()
        size = [size for size in sizes if (not flavor_id) or (size.id == flavor_id)][0]

        node = conn.create_node(name=hostname,
                                image=image,
                                size=size,
                                key_name=key_name)

        iteration_node = node
        while iteration_node.state is not NodeState.RUNNING:
            time.sleep(1)
            iteration_node = [n for n in conn.list_nodes() if n.uuid == node.uuid][0]

        conn.ex_add_floating_ip(node, self.public_ip)
        return node

    def __get_connection(self):
        driver = get_driver(Provider.OPENSTACK)
        openstack_api_host = self.options['openstack']['api_host']
        openstack_username = self.options['openstack']['username']
        openstack_api_key = self.options['openstack']['api_key']
        openstack_tennant_id = self.options['openstack']['tennant_id']

        auth_url = 'http://%s:5000' % openstack_api_host
        base_url = 'http://%s:8774/v1.1/%s/' % (openstack_api_host, openstack_tennant_id)
        conn = driver(openstack_username,
                      openstack_api_key,
                      False,
                      host=openstack_api_host,
                      port=8774,
                      ex_force_auth_url=auth_url,
                      ex_force_auth_version='1.0',
                      ex_force_base_url=base_url)
        return conn


class Ec2VmLauncher(VmLauncher):

    def __init__(self, options):
        VmLauncher.__init__(self, options)

    def get_ip(self):
        return self._wait_for_node_info(lambda node: node.extra['dns_name'])

    def connect_driver(self):
        self.conn = self.__get_connection()
        return self.conn

    def package(self):
        env.packaging_dir = "/mnt/packaging"
        sudo("mkdir -p %s" % env.packaging_dir)
        self._copy_keys()
        self._install_ec2_tools()
        self._install_packaging_scripts()

    def _install_ec2_tools(self):
        sudo("apt-add-repository ppa:awstools-dev/awstools")
        sudo("apt-get update")
        sudo('export DEBIAN_FRONTEND=noninteractive; sudo -E apt-get install ec2-api-tools ec2-ami-tools -y --force-yes')

    def _install_packaging_scripts(self):
        user_id = self.options["aws"]["user_id"]
        bundle_cmd = "sudo ec2-bundle-vol -k %s/ec2_key -c%s/ec2_cert -u %s" % \
            (env.packaging_dir, env.packaging_dir, user_id)
        self._write_script("%s/bundle_image.sh" % env.packaging_dir, bundle_cmd)

        bucket = self.options["aws"]["package_bucket"]
        upload_cmd = "sudo ec2-upload-bundle -b %s -m /tmp/image.manifest.xml -a %s -s %s" % \
            (bucket,  self._access_id(), self._secret_key())
        self._write_script("%s/upload_bundle.sh" % env.packaging_dir, upload_cmd)

        name = self.options["aws"]["package_image_name"]
        manifest = "image.manifest.xml"
        register_cmd = "sudo ec2-register -K %s/ec2_key -C %s/ec2_cert %s/%s -n %s" % (env.packaging_dir, env.packaging_dir, bucket, manifest, name)
        self._write_script("%s/register_bundle.sh" % env.packaging_dir, register_cmd)

    def _write_script(self, path, contents):
        full_contents = "#!/bin/bash\n%s" % contents
        sudo("echo '%s' > %s" % (full_contents, path))
        sudo("chmod +x %s" % path)

    def _copy_keys(self):
        ec2_key_path = self.options["aws"]["x509_key"]
        ec2_cert_path = self.options["aws"]["x509_cert"]
        put(ec2_key_path, "%s/ec2_key" % env.packaging_dir, use_sudo=True)
        put(ec2_cert_path, "%s/ec2_cert" % env.packaging_dir, use_sudo=True)

    def _boot(self):
        conn = self.conn
        if 'use_existing_instance' in self.options["aws"]:
            instance_id = self.options['aws']['use_existing_instance']
            nodes = conn.list_nodes()
            for node in nodes:
                print node.uuid
                if node.uuid == instance_id:
                    return node
            raise Exception("Could not find instance with id %s" % instance_id)

        if "image_id" in self.options["aws"]:
            image_id = self.options["aws"]["image_id"]
        else:
            image_id = DEFAULT_AWS_IMAGE_ID

        if "size_id" in self.options["aws"]:
            size_id = self.options["aws"]["size_id"]
        else:
            size_id = DEFAULT_AWS_SIZE_ID
        if "availability_zone" in self.options["aws"]:
            availability_zone = self.options["aws"]["availability_zone"]
        else:
            availability_zone = DEFAULT_AWS_AVAILABILITY_ZONE

        image = NodeImage(id=image_id, name="", driver="")
        size = NodeSize(id=size_id, name="", ram=None, disk=None, bandwidth=None, price=None, driver="")
        locations = conn.list_locations()
        for location in locations:
            if location.availability_zone.name == availability_zone:
                break
        keyname = self.options["aws"]["keypair_name"]
        hostname = self.options["hostname"]
        node = conn.create_node(name=hostname,
                                image=image,
                                size=size,
                                location=location,
                                ex_keyname=keyname)
        return node

    def __get_connection(self):
        driver = get_driver(Provider.EC2)
        ec2_access_id = self._access_id()
        ec2_secret_key = self._secret_key()
        conn = driver(ec2_access_id, ec2_secret_key)
        return conn

    def _access_id(self):
        return self.options["aws"]["ec2_access_id"]

    def _secret_key(self):
        return self.options["aws"]["ec2_secret_key"]


def build_vm_launcher(options):
    vm_host = options['vm_host']
    if vm_host and vm_host == 'openstack':
        vm_launcher = OpenstackVmLauncher(options)
    elif vm_host and vm_host == 'vagrant':
        vm_launcher = VagrantVmLauncher(options)
    else:
        vm_launcher = Ec2VmLauncher(options)
    return vm_launcher
