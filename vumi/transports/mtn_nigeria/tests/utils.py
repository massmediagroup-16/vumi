import struct

from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.internet.protocol import Factory, ClientCreator

from vumi.transports.mtn_nigeria.xml_over_tcp import XmlOverTcpClient

_header_size = XmlOverTcpClient.HEADER_SIZE
_length_header_size = XmlOverTcpClient.LENGTH_HEADER_SIZE
_header_format = XmlOverTcpClient.HEADER_FORMAT


def mk_packet(session_id, body):
    length = len(body) + _header_size
    header = struct.pack(
        _header_format,
        session_id.encode(),
        str(length).zfill(_length_header_size))
    return header + body


class WaitForDataMixin(object):
    waiting_for_data = False
    deferred_data = Deferred()

    def wait_for_data(self):
        d = Deferred()
        self.deferred_data = d
        self.waiting_for_data = True
        return d

    def callback_deferred_data(self, data):
        if self.waiting_for_data and not self.deferred_data.called:
            self.waiting_for_data = False
            self.deferred_data.callback(data)


class MockServerFactory(Factory):
    def __init__(self):
        self.deferred_server = Deferred()


class MockServer(Protocol):
    def connectionMade(self):
        self.factory.deferred_server.callback(self)


class MockServerMixin(object):
    server_protocol = None

    @inlineCallbacks
    def start_server(self):
        factory = MockServerFactory()
        factory.protocol = self.server_protocol
        self.server_port = reactor.listenTCP(0, factory)
        self.server = yield factory.deferred_server

    def stop_server(self):
        return self.server_port.loseConnection()

    def get_server_port(self):
        return self.server_port.getHost().port


class MockXmlOverTcpServer(MockServer, WaitForDataMixin):
    def __init__(self):
        self.responses = {}

    def send_data(self, data):
        self.transport.write(data)

    def dataReceived(self, data):
        response = self.responses.get(data)
        if response is not None:
            self.transport.write(response)
        self.callback_deferred_data(data)


class MockXmlOverTcpServerMixin(MockServerMixin):
    server_protocol = MockXmlOverTcpServer


class MockClientMixin(object):
    client_protocol = None

    @inlineCallbacks
    def start_client(self, port):
        self.client_creator = ClientCreator(reactor, self.client_protocol)
        self.client = yield self.client_creator.connectTCP('127.0.0.1', port)

    def stop_client(self):
        return self.client.transport.loseConnection()


class MockClientServerMixin(MockClientMixin, MockServerMixin):
    @inlineCallbacks
    def start_protocols(self):
        deferred_server = self.start_server()
        yield self.start_client(self.get_server_port())
        yield deferred_server  # we need to wait for the client to connect

    @inlineCallbacks
    def stop_protocols(self):
        yield self.stop_client()
        yield self.stop_server()
