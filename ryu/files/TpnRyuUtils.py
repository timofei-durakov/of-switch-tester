from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller import dpset
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import dpid as dpid_lib
from ryu.app.wsgi import ControllerBase, WSGIApplication, route, Response
from ryu.lib.packet import ethernet, ipv4, udp, packet
from ryu.ofproto import ether, inet


SWITCHID_PATTERN = dpid_lib.DPID_PATTERN + r'|all'
VLANID_PATTERN = r'[0-9]{1,4}|all'
REQUIREMENTS = {'switchid': SWITCHID_PATTERN,
                'vlanid': VLANID_PATTERN}

DL_DST = '11:22:33:44:55:66'
DL_SRC = '66:55:44:33:22:11'
DL_TYPE = ether.ETH_TYPE_IP
IP_SRC = '1.1.1.1'
IP_DST = '2.2.2.2'
IP_PROTO = inet.IPPROTO_UDP

pipeline_tester_instance_name = "PipelineTesterInstance"


def make_packet(pkt_size):
    e = ethernet.ethernet(DL_DST, DL_SRC, DL_TYPE)
    i = ipv4.ipv4(total_length=0, src=IP_SRC, dst=IP_DST, proto=IP_PROTO, ttl=1)
    u = udp.udp(src_port=5000, dst_port=10000)
    payload_size = pkt_size - (len(e) + len(i) + len(u))
    payload = bytearray(payload_size if payload_size > 0 else 0)

    p = packet.Packet()
    p.add_protocol(e)
    p.add_protocol(i)
    p.add_protocol(u)
    p.add_protocol(payload)

    return p


class TpnRyuUtils(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {
                'dpset': dpset.DPSet,
                'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(TpnRyuUtils, self).__init__(*args, **kwargs)
        self.dpset = kwargs['dpset']
        wsgi = kwargs['wsgi']
        wsgi.register(PipelineTesterController, {pipeline_tester_instance_name: self})

    def send_packet(self, dpid, pkt, port):
        dp = self.dpset.get(dpid)
        ofp = dp.ofproto
        ofp_parser = dp.ofproto_parser
        port = ofp.OFPP_FLOOD if port < 0 else port
        actions = [ofp_parser.OFPActionOutput(port)]
        req = ofp_parser.OFPPacketOut(dp,
                                      in_port=ofp.OFPP_CONTROLLER,
                                      buffer_id=ofp.OFP_NO_BUFFER,
                                      actions=actions,
                                      data=pkt)
        dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_event_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.logger.info('register datapath: %016x', datapath.id)
        elif ev.state == DEAD_DISPATCHER:
            self.logger.info('unregister datapath: %016x', datapath.id)
        else:
            self.logger.error("Somehow %016x unregistered with us but was never registered", datapath.id)


class PipelineTesterController(ControllerBase):

    def __init__(self, req, link, data, **config):
        super(PipelineTesterController, self).__init__(req, link, data, **config)
        self.pipeline_tester_app = data[pipeline_tester_instance_name]

    @route('tester', '/tpn/packet_out/{switchid}/{port}/{pkt_size}/{count}', methods=['POST'])
    def send_packetout(self, req, **kwargs):
        app = self.pipeline_tester_app
        switchid = int(kwargs['switchid'], 0)
        pkt_size = int(kwargs['pkt_size'], 0)
        port = int(kwargs['port'], 0)

        count = 1
        if 'count' in kwargs:
            count = int(kwargs['count'], 0)

        p = make_packet(pkt_size)
        while count > 0:
            app.send_packet(switchid, p, port)
            count -= 1
