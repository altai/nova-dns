#!/usr/bin/python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Nova DNS Copyright (C) GridDynamics Openstack Core Team, GridDynamics
#
#    This program is free software: you can redistribute it and/or modify it
#    under the terms of the GNU Lesser General Public License as published by
#    the Free Software Foundation, either version 2.1 of the License, or (at
#    your option) any later version.
#
#    This program is distributed in the hope that it will be useful, but
#    WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
#    or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public
#    License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program.  If not, see <http://www.gnu.org/licenses/>.


"""Simple Instance Manager"""


import socket
import netaddr

from nova import utils
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg

from nova_dns.dnsmanager import DNSRecord
from nova_dns.instance_manager import InstanceManager
from nova_dns.auth import AUTH


LOG = logging.getLogger("nova_dns.instance_manager.simple")
FLAGS = flags.FLAGS

#TODO make own zone for every instance
opts = [
    cfg.ListOpt("dns_ns", default=["ns1:127.0.0.1"],
                help="Name servers, in format ns1:ip1, ns2:ip2"),
    cfg.BoolOpt('dns_ptr', default=False, help='Manage PTR records'),
    cfg.ListOpt('dns_ptr_zones', default=[],
                help="Classless delegation networks in format ip_addr/network")
]
FLAGS.register_opts(opts)


class SimpleInstanceManager(InstanceManager):

    def __init__(self):
        dnsmanager_class = utils.import_class(FLAGS.dns_manager)
        self.dnsmanager = dnsmanager_class()

    def add_instance(self, hostname, tenant_id, network_id, address):
        zones_list = self.dnsmanager.list()
        if FLAGS.dns_zone not in zones_list:
            #Lazy create main zone and populate by ns
            self._add_main_zone()
        zonename = AUTH.tenant2zonename(tenant_id)
        if zonename not in zones_list:
            self._add_zone(zonename)
        try:
            self.dnsmanager.get(zonename).add(
                DNSRecord(name=hostname, type='A', content=address))
            if FLAGS.dns_ptr:
                (ptr_zonename, octet) = self.ip2zone(address)
                if ptr_zonename not in zones_list:
                    self._add_zone(ptr_zonename)
                self.dnsmanager.get(ptr_zonename).add(DNSRecord(name=octet,
                    type='PTR', content=hostname + '.' + zonename))
        except ValueError as e:
            LOG.warn(str(e))

    def delete_instance(self, hostname, tenant_id, network_id, address):
        #TODO check if record was added/changed by admin
        zonename = AUTH.tenant2zonename(tenant_id)
        zone = self.dnsmanager.get(zonename)
        if FLAGS.dns_ptr:
            ip = zone.get(hostname, 'A')[0].content
            (ptr_zonename, octet) = self.ip2zone(ip)
            self.dnsmanager.get(ptr_zonename).delete(str(octet), 'PTR')
        zone.delete(hostname, 'A')

    def _add_main_zone(self):
        name = FLAGS.dns_zone
        self._add_zone(name)
        zone = self.dnsmanager.get(name)
        for ns in FLAGS.dns_ns:
            (host, address) = ns.split(':', 1)
            # NOTE(imelnikov): if host is in main zone or its subdomain,
            #   strip current zone and period
            if host.endswith(name):
                host = host[:-len(name) - 1]
            if '.' not in host:
                # NOTE(imelnikov): this is host from main zone,
                #    let's add a record for it
                try:
                    socket.inet_aton(address)
                    # ok, this is something like ipv4
                    record_type = 'A'
                except socket.error:
                    # this is not ipv4, must be host name
                    record_type = 'PTR'
                zone.add(DNSRecord(name=host, type=record_type,
                                   content=address))

    def _add_zone(self, name):
        try:
            self.dnsmanager.add(name)
        except ZoneExists:
            return
        zone = self.dnsmanager.get(name)
        for ns in FLAGS.dns_ns:
            (host, _address) = ns.split(':', 2)
            if '.' not in host:
                host = '%s.%s' % (host, FLAGS.dns_zone)
            zone.add(DNSRecord(name=name, type="NS", content=host))

    def ip2zone(self, ip):
        #TODO check /cidr >= 24
        addr = netaddr.IPAddress(ip)
        for zone in FLAGS.dns_ptr_zones:
            #TODO prepare netaddr one time on service start
            zoneaddr = netaddr.IPNetwork(zone)
            if addr not in zoneaddr:
                continue
            cidr = str(zoneaddr.cidr).split('/')[1]
            w = zoneaddr.cidr.ip.words
            return ("%s-%s.%s.%s.%s.in-addr.arpa" %
                (w[3], cidr, w[2], w[1], w[0]), addr.words[-1])
        w = addr.words
        return ("%s.%s.%s.in-addr.arpa" % (w[2], w[1], w[0]), w[3])

