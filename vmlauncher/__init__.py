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

    def __init__(self, driver_type, options):
        self.options = options
        self.driver_type = driver_type
        self.__set_and_verify_key()

    def __set_and_verify_key(self):
        self.key_file = self.options['key_file']
        if not os.path.exists(self.key_file):
            raise Exception("Invalid or unspecified key_file options: %s" % self.key_file)

    def _get_driver_options(self, driver_option_keys):
        driver_options = {}
        for key in driver_option_keys:
            if key in self._driver_options():
                driver_options[key] = self._driver_options()[key]
        return driver_options

    def _driver_options(self):
        return self.options[self.driver_type]

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
            return self._parse_node_info(initial_value)
        while True:
            time.sleep(10)
            refreshed_node = self._find_node()
            refreshed_value = f(refreshed_node)
            if refreshed_value and not refreshed_value == []:
                return self._parse_node_info(refreshed_value)

    def _parse_node_info(self, value):
        if isinstance(value, basestring):
            return value
        else:
            return value[0]

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

    def _boot(self):
        conn = self.conn
        if 'use_existing_instance' in self._driver_options():
            instance_id = self._driver_options()['use_existing_instance']
            nodes = conn.list_nodes()
            node = [node for node in nodes if node.uuid == instance_id][0]
            if not node:
                raise Exception("Failed to find instance of uuid %s" % instance_id)
        else:
            node = self._boot_new(conn)
        return node


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
        if not 'key_file' in options:
            options['key_file'] = os.path.join(os.environ["HOME"], ".vagrant.d", "insecure_private_key")
        VmLauncher.__init__(self, 'vagrant', options)
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
        VmLauncher.__init__(self, 'openstack', options)

    def connect_driver(self):
        self.conn = self.__get_connection()
        return self.conn

    def get_ip(self):
        return self._wait_for_node_info(lambda node: node.public_ips + node.private_ips)

    def _boot_new(self, conn):
        if 'image_id' in self._driver_options():
            image_id = self._driver_options()['image_id']
        else:
            image_id = None
        if self._driver_options():
            flavor_id = self._driver_options()['flavor_id']
        else:
            flavor_id = None
        ex_keyname = self._driver_options()['ex_keyname']
        hostname = self.options['hostname']

        images = conn.list_images()
        image = [image for image in images if (not image_id) or (image.id == image_id)][0]
        sizes = conn.list_sizes()
        try:
            size = [size for size in sizes if (not flavor_id) or (str(size.id) == str(flavor_id))][0]
        except IndexError, e:
            print "Cloudn't find flavor with id %s in flavors %s" % (flavor_id, sizes)
            size = sizes[0]

        node = conn.create_node(name=hostname,
                                image=image,
                                size=size,
                                ex_keyname=ex_keyname)

        iteration_node = node
        while iteration_node.state is not NodeState.RUNNING:
            time.sleep(1)
            iteration_node = [n for n in conn.list_nodes() if n.uuid == node.uuid][0]

        #conn.ex_add_floating_ip(node, self.public_ip)
        return node

    def __get_connection(self):
        driver = get_driver(Provider.OPENSTACK)
        openstack_username = self._driver_options()['username']
        openstack_api_key = self._driver_options()['password']

        driver_option_keys = ['host',
                              'secure',
                              'port',
                              'ex_force_auth_url',
                              'ex_force_auth_version',
                              'ex_force_base_url',
                              'ex_tenant_name']

        driver_options = self._get_driver_options(driver_option_keys)
        conn = driver(openstack_username,
                      openstack_api_key,
                      **driver_options)
        return conn

    def package(self):
        name = self._driver_options()["package_image_name"] or "cloudbiolinux"
        self.conn.ex_save_image(self.node, name)


class EucalyptusVmLauncher(VmLauncher):

    def __init__(self, options):
        VmLauncher.__init__(self, 'eucalyptus', options)

    def get_ip(self):
        return self._wait_for_node_info(lambda node: node.public_ips)

    def connect_driver(self):
        self.conn = self.__get_connection()
        return self.conn

    def __get_connection(self):
        driver = get_driver(Provider.EUCALYPTUS)
        driver_option_keys = ['secret',
                              'secure',
                              'port',
                              'host',
                              'path']

        driver_options = self._get_driver_options(driver_option_keys)
        ec2_access_id = self._access_id()
        conn = driver(ec2_access_id, **driver_options)
        return conn

    def _access_id(self):
        return self._driver_options()["ec2_access_id"]

    def _boot_new(self, conn):
        image_id = self._driver_options()["image_id"]
        size_id = self._driver_options()["size_id"]

        image = NodeImage(id=image_id, name="", driver="")
        size = NodeSize(id=size_id, name="", ram=None, disk=None, bandwidth=None, price=None, driver="")

        keyname = self._driver_options()["keypair_name"]
        hostname = self.options["hostname"]
        node = conn.create_node(name=hostname,
                                image=image,
                                size=size,
                                ex_keyname=keyname)
        return node


class Ec2VmLauncher(VmLauncher):

    def __init__(self, options):
        VmLauncher.__init__(self, 'aws', options)

    def get_ip(self):
        return self._wait_for_node_info(lambda node: node.extra['dns_name'])

    def connect_driver(self):
        self.conn = self.__get_connection()
        return self.conn

    def boto_connection(self):
        """
        Establish a boto library connection (for functionality not available in libcloud).
        """
        import boto.ec2
        region = boto.ec2.get_region(self._availability_zone())
        ec2_access_id = self._access_id()
        ec2_secret_key = self._secret_key()
        return region.connect(aws_access_key_id=ec2_access_id, aws_secret_access_key=ec2_secret_key)

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
        user_id = self._driver_options()["user_id"]
        bundle_cmd = "sudo ec2-bundle-vol -k %s/ec2_key -c%s/ec2_cert -u %s" % \
            (env.packaging_dir, env.packaging_dir, user_id)
        self._write_script("%s/bundle_image.sh" % env.packaging_dir, bundle_cmd)

        bucket = self._driver_options()["package_bucket"]
        upload_cmd = "sudo ec2-upload-bundle -b %s -m /tmp/image.manifest.xml -a %s -s %s" % \
            (bucket,  self._access_id(), self._secret_key())
        self._write_script("%s/upload_bundle.sh" % env.packaging_dir, upload_cmd)

        name = self.package_image_name()

        manifest = "image.manifest.xml"
        register_cmd = "sudo ec2-register -K %s/ec2_key -C %s/ec2_cert %s/%s -n %s" % (env.packaging_dir, env.packaging_dir, bucket, manifest, name)
        self._write_script("%s/register_bundle.sh" % env.packaging_dir, register_cmd)

    def package_image_name(self):
        name = self._driver_options()["package_image_name"]
        return name

    def package_image_description(self, default=""):
        description = self._driver_options().get("package_image_description", default)
        return description

    def _write_script(self, path, contents):
        full_contents = "#!/bin/bash\n%s" % contents
        sudo("echo '%s' > %s" % (full_contents, path))
        sudo("chmod +x %s" % path)

    def _copy_keys(self):
        ec2_key_path = self._driver_options()["x509_key"]
        ec2_cert_path = self._driver_options()["x509_cert"]
        put(ec2_key_path, "%s/ec2_key" % env.packaging_dir, use_sudo=True)
        put(ec2_cert_path, "%s/ec2_cert" % env.packaging_dir, use_sudo=True)

    def _availability_zone(self):
        if "availability_zone" in self._driver_options():
            availability_zone = self._driver_options()["availability_zone"]
        else:
            availability_zone = DEFAULT_AWS_AVAILABILITY_ZONE
        return availability_zone

    def _boot_new(self, conn):
        if "image_id" in self._driver_options():
            image_id = self._driver_options()["image_id"]
        else:
            image_id = DEFAULT_AWS_IMAGE_ID

        if "size_id" in self._driver_options():
            size_id = self._driver_options()["size_id"]
        else:
            size_id = DEFAULT_AWS_SIZE_ID

        availability_zone = self._availability_zone()
        image = NodeImage(id=image_id, name="", driver="")
        size = NodeSize(id=size_id, name="", ram=None, disk=None, bandwidth=None, price=None, driver="")
        locations = conn.list_locations()
        for location in locations:
            if location.availability_zone.name == availability_zone:
                break
        keyname = self._driver_options()["keypair_name"]
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
        return self._driver_options()["ec2_access_id"]

    def _secret_key(self):
        return self._driver_options()["ec2_secret_key"]


def build_vm_launcher(options):
    vm_host = options['vm_host']
    if vm_host and vm_host == 'openstack':
        vm_launcher = OpenstackVmLauncher(options)
    elif vm_host and vm_host == 'vagrant':
        vm_launcher = VagrantVmLauncher(options)
    elif vm_host and vm_host == 'eucalyptus':
        vm_launcher = EucalyptusVmLauncher(options)
    else:
        vm_launcher = Ec2VmLauncher(options)
    return vm_launcher
