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
import sqlalchemy.engine

from nova import utils
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg

from nova_dns import exc
from nova_dns.dnsmanager import DNSRecord
from nova_dns.instance_manager import InstanceManager
from nova_dns.auth import AUTH


LOG = logging.getLogger("nova_dns.instance_manager.simple")
FLAGS = flags.FLAGS

#TODO make own zone for every instance
opts = [
    cfg.StrOpt('dns_zone_address', default='none',
               help="IPv4 address dns_zone should be resolved to. "
               "'A' or 'PTR' record with empty name will be added "
               "to root zone for it. Set to 'none' (the default) or "
               "empty string to disable this behavior."),
    cfg.ListOpt("dns_ns", default=["ns1:127.0.0.1"],
                help="Name servers, in format ns1:ip1, ns2:ip2"),
    cfg.BoolOpt('dns_ptr', default=False, help='Manage PTR records'),
    cfg.ListOpt('dns_ptr_zones', default=[],
                help="Classless delegation networks in format ip_addr/network")
]
FLAGS.register_opts(opts)


def _ip_to_zone(ip):
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


class SimpleInstanceManager(InstanceManager):

    def __init__(self):
        dnsmanager_class = utils.import_class(FLAGS.dns_manager)
        self.dnsmanager = dnsmanager_class()
        self.conn = sqlalchemy.engine.create_engine(FLAGS.sql_connection,
            pool_recycle=FLAGS.sql_idle_timeout, echo=False)

    def add_instance(self, hostname, tenant_id, network_id, address):
        zonename = AUTH.tenant2zonename(tenant_id)
        zone = self._zone_get_or_create(zonename)
        try:
            self._add_record_if_not_present(zone, hostname, 'A', address)
            if FLAGS.dns_ptr:
                (ptr_zonename, octet) = _ip_to_zone(address)
                self._add_record_if_not_present(
                        self._zone_get_or_create(ptr_zonename),
                        str(octet), 'PTR', '.'.join((hostname, zonename)))
        except ValueError as e:
            LOG.warn(str(e))

    def delete_instance(self, hostname, tenant_id, network_id, address):
        #TODO check if record was added/changed by admin
        zonename = AUTH.tenant2zonename(tenant_id)
        try:
            zone = self.dnsmanager.get(zonename)
            if address is None:
                address = zone.get(hostname, 'A')[0].content
            zone.delete(hostname, 'A')
        except (exc.ZoneNotFound, exc.RecordNotFound):
            pass

        if FLAGS.dns_ptr:
            try:
                (ptr_zonename, octet) = _ip_to_zone(address)
                self.dnsmanager.get(ptr_zonename).delete(str(octet), 'PTR')
            except (exc.ZoneNotFound, exc.RecordNotFound):
                pass

    @staticmethod
    def _add_record_if_not_present(zone, name, type, content):
        if not any(r.content == content for r in zone.get(name, type)):
            zone.add(DNSRecord(name=name, type=type, content=content))

    def _make_record(self, name, address):
        try:
            socket.inet_aton(address)
            # ok, this is something like ipv4
            record_type = 'A'
        except socket.error:
            # this is not ipv4, must be host name
            record_type = 'PTR'
        return DNSRecord(name=name, type=record_type, content=address)

    def _zone_get_or_create(self, name):
        try:
            return self.dnsmanager.get(name)
        except exc.ZoneNotFound:
            pass
        if name != FLAGS.dns_zone:
            self._zone_get_or_create(FLAGS.dns_zone)
        LOG.info("Creating new zone %r", name)
        self.dnsmanager.add(name)
        zone = self.dnsmanager.get(name)
        for ns in FLAGS.dns_ns:
            (host, _address) = ns.split(':', 2)
            if '.' not in host:
                host = '%s.%s' % (host, FLAGS.dns_zone)
            zone.add(DNSRecord(name='', type="NS", content=host))

        if name == FLAGS.dns_zone:
            if FLAGS.dns_zone_address not in ('', 'none'):
                zone.add(self._make_record('', FLAGS.dns_zone_address))
            for ns in FLAGS.dns_ns:
                (host, address) = ns.split(':', 1)
                # NOTE(imelnikov): if host is in main zone or its subdomain,
                #   strip current zone and period
                if host.endswith(name):
                    host = host[:-len(name) - 1]
                if '.' not in host:
                    # NOTE(imelnikov): this is host from main zone,
                    #    let's add a record for it
                    zone.add(self._make_record(host, address))
        return zone

    def sync(self, zone=None):
        if zone:
            LOG.info("Synchronizing zone %r", zone)
            records = {zone: []}
        else:
            LOG.info("Synchronizing all zones")
            records = dict((name, []) for name in self.dnsmanager.list())

        for r in self.conn.execute(
                'SELECT i.hostname, i.project_id, f.address '
                'FROM instances i, fixed_ips f '
                'WHERE i.id=f.instance_id '
                '  AND i.deleted=0'):
            fwd_zone = AUTH.tenant2zonename(r.project_id)
            if zone is None or zone == fwd_zone:
                records.setdefault(fwd_zone, []).append(
                    DNSRecord(r.hostname, 'A', r.address))
            ptr_zone, octet = _ip_to_zone(r.address)
            if zone is None or zone == ptr_zone:
                fqdn = '.'.join((r.hostname, fwd_zone))
                records.setdefault(ptr_zone, []).append(
                    DNSRecord(octet, 'PTR', fqdn))

        for zone_name, zone_records in records.iteritems():
            if zone_name == FLAGS.dns_zone:
                continue
            z = self._zone_get_or_create(zone_name)
            try:
                z.delete(name=None, type='PTR')
            except exc.RecordNotFound:
                pass
            try:
                z.delete(name=None, type='A')
            except exc.RecordNotFound:
                pass
            for r in zone_records:
                z.add(r)
        LOG.info("Synchronizing finished successfully")
        return "ok"
