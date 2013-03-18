# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2013 Grid Dynamics Consulting Services, Inc
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from nova import db
from nova import flags
from nova import utils
from nova import log as logging
from nova_dns.auth import AUTH

from nova.network.linux_net import (update_dhcp_hostfile_with_text,
                                    restart_dhcp)

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


class NovaDnsNetworkDriver(object):
    """Network driver for nova-network

    Delegates most of the work to linux_net providing special
    DHCP configuration that works nicely with nova-dns.

    """

    def __init__(self, base_driver=None):
        if base_driver is None:
            base_driver = 'nova.network.linux_net'
        self._base = utils.import_object(base_driver)
        if hasattr(self._base, 'ensure_vpn_forward'):
            self.ensure_vpn_forward = self._base.ensure_vpn_forward

    def get_dev(self, network):
        """Part of network driver contract delegated to base driver"""
        return self._base.get_dev(network)

    def get_dhcp_leases(self, context, network_ref):
        """Part of network driver contract delegated to base driver"""
        return self._base.get_dhcp_leases(context, network_ref)

    def update_ra(self, context, dev, network_ref):
        """Part of network driver contract delegated to base driver"""
        return self._base.update_ra(context, dev, network_ref)

    def release_dhcp(self, dev, address, mac_address):
        """Part of network driver contract delegated to base driver"""
        return self._base.release_dhcp(dev, address, mac_address)

    def kill_dhcp(self, dev):
        """Part of network driver contract delegated to base driver"""
        return self._base.kill_dhcp(dev)

    def update_dhcp_hostfile_with_text(self, dev, hosts_text):
        """Part of network driver contract delegated to base driver"""
        return self._base.update_dhcp_hostfile_with_text(dev, hosts_text)

    def metadata_accept(self):
        """Part of network driver contract delegated to base driver"""
        return self._base.metadata_accept()

    # NOTE(imelnikov): interesting part starts here

    def restart_dhcp(self, context, dev, network_ref):
        """Restart DHCP daemon

        We pass additional parameter, DHCP domain, to it.

        """
        # NOTE(imelnikov): this requires patched nova
        return restart_dhcp(context, dev, network_ref,
                            dhcp_domain=self._get_network_domain(network_ref))

    def update_dhcp(self, context, dev, network_ref):
        if FLAGS.use_single_default_gateway:
            LOG.error("Cannot use AltaiNetworkDriver with "
                      "FLAGS.use_single_default_gateway")
            return self._base.update_dhcp(context, dev, network_ref)
        data = self._get_dhcp_hosts(context, network_ref)
        self.update_dhcp_hostfile_with_text(dev, data)
        self.restart_dhcp(context, dev, network_ref)

    def _get_dhcp_hosts(self, context, network_ref):
        """Get network's hosts config in dhcp-host format."""
        hosts = []
        host = None
        if network_ref['multi_host']:
            host = FLAGS.host
        network_domain = self._get_network_domain(network_ref)
        for data in db.network_get_associated_fixed_ips(context,
                                                        network_ref['id'],
                                                        host=host):
            hosts.append('%s,%s.%s,%s' % (data['vif_address'],
                                          data['instance_hostname'],
                                          network_domain,
                                          data['address']))
        return '\n'.join(hosts)

    def _get_network_domain(self, network_ref):
        return AUTH.tenant2zonename(network_ref['project_id'])

