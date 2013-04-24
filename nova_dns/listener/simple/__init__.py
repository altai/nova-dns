#!/usr/bin/python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Nova DNS
#    Copyright (C) GridDynamics Openstack Core Team, GridDynamics
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as published
#    by the Free Software Foundation, either version 2.1 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Simple listener:
- doesn't sync state with dns after restart
- stateless"""


import time
import eventlet
import sqlalchemy.engine

from nova import log as logging
from nova import utils
from nova import flags

from nova_dns.listener import AMQPListener


LOG = logging.getLogger("nova_dns.listener.simple")
FLAGS = flags.FLAGS
SLEEP = 60

start_vm = frozenset(['run_instance', 'start_instance'])
stop_vm = frozenset(['terminate_instance', 'stop_instance'])


class Listener(AMQPListener):
    def __init__(self):
        self.pending = {}
        self.conn = sqlalchemy.engine.create_engine(FLAGS.sql_connection,
            pool_recycle=FLAGS.sql_idle_timeout, echo=False)
        self.instance_manager = utils.import_object(FLAGS.dns_instance_manager)
        self.eventlet = eventlet.spawn(self._pollip)

    def event(self, e):
        method = e.get("method", "<unknown>")
        id = e["args"].get("instance_uuid", None)
        if method in start_vm:
            LOG.info("Run instance %s. Waiting on assing ip address" % (str(id),))
            self.pending[id] = 1
        elif method in stop_vm:
            if id in self.pending:
                del self.pending[id]
            for r in self.conn.execute(
                    'SELECT i.hostname, i.project_id, f.address '
                    'FROM instances i, fixed_ips f '
                    'WHERE i.id=f.instance_id AND i.uuid = %s', id):
                try:
                    LOG.info("Instance %s hostname '%s' was terminated",
                             id, r.hostname)
                    # TODO(imelnikov): pass real network ID
                    self.instance_manager.delete_instance(
                        r.hostname, r.project_id, None, r.address)
                except Exception:
                    LOG.exception("Failed to delete instance")
        else:
            LOG.debug("Skip message with method: %s", method)

    def _pollip(self):
        while True:
            time.sleep(SLEEP)
            if not len(self.pending):
                continue
            #TODO change select to i.id in ( pendings ) to speed up
            for r in self.conn.execute("""
                select i.hostname, i.id, i.project_id, i.uuid, f.address
                from instances i, fixed_ips f
                where i.id=f.instance_id"""):
                if r.uuid not in self.pending:
                    continue
                LOG.info("Instance %s hostname %s adding ip %s" %
                    (r.uuid, r.hostname, r.address))
                del self.pending[r.uuid]
                # TODO(imelnikov): pass real network ID
                try:
                    self.instance_manager.add_instance(
                        r.hostname, r.project_id, None, r.address)
                except Exception:
                    LOG.exception("Failed to add instance")
