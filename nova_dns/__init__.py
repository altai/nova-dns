
__version__ = "0.3.2"

try:
    from nova import flags
    from nova.openstack.common import cfg

    FLAGS = flags.FLAGS

    opts = [
	cfg.StrOpt("dns_manager", default="nova_dns.dnsmanager.powerdns.Manager",
			    help="DNS manager class"),
	cfg.StrOpt("dns_listener", default="nova_dns.listener.simple.Listener",
			    help="Class to process AMQP messages"),
	cfg.StrOpt("dns_api_paste_config", default="/etc/nova-dns/dns-api-paste.ini",
			    help="File name for the paste.deploy config for nova-dns api")
    ]
    FLAGS.register_opts(opts)
    
except:
    #make setup.py happy
    pass

