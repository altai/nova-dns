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


"""Exception classes for nova_dns"""


class NovaDNSException(Exception):
    pass


class ZoneAlreadyExists(NovaDNSException):
    def __init__(self, name, *args, **kwargs):
        super(ZoneAlreadyExists, self).__init__(
                'Zone %r already exists' % name, *args, **kwargs)


class ZoneNotFound(NovaDNSException):
    def __init__(self, name, *args, **kwargs):
        super(ZoneNotFound, self).__init__(
                'Zone not found: %r' % name, *args, **kwargs)


class ZoneNotEmpty(NovaDNSException):
    pass


class RecordNotFound(NovaDNSException):
    def __init__(self, name, record_type, *args, **kwargs):
        if record_type is not None:
            msg = 'Record %r of type %r does not exist' % (name, record_type)
        else:
            msg = 'Records not found: %r' % name
        super(RecordNotFound, self).__init__(msg, *args, **kwargs)
