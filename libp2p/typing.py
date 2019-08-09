from typing import Awaitable, Callable, Dict, List, NewType, Tuple, Union

from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.stream_muxer.abc import IMuxedStream

TProtocol = NewType("TProtocol", str)
StreamHandlerFn = Callable[[INetStream], Awaitable[None]]

NegotiableTransport = Union[IMuxedStream, IRawConnection]

IP = NewType("IP", str)
Port = NewType("Port", int)
Address = Tuple[IP, Port]

PeerIDBytes = NewType("PeerIDBytes", bytes)

# Kademlia
DHTValue = PeerIDBytes
KadPeerTuple = Tuple[PeerIDBytes, IP, Port]
FindNodeResponse = List[KadPeerTuple]
FindValueResponse = Dict[str, DHTValue]
FindXResponse = Union[FindNodeResponse, FindValueResponse]
RPCSuccessful = NewType("RPCSuccessful", bool)
