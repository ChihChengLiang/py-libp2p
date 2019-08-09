from typing import Awaitable, Callable, Dict, NewType, Sequence, Tuple, Union

from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.stream_muxer.abc import IMuxedStream

TProtocol = NewType("TProtocol", str)
StreamHandlerFn = Callable[[INetStream], Awaitable[None]]

NegotiableTransport = Union[IMuxedStream, IRawConnection]

IP = NewType("IP", str)
Port = NewType("Port", int)
Address = NewType("Address", Tuple[IP, Port])

PeerIDBytes = NewType("PeerIDBytes", bytes)

# Kademlia
DHTValue = NewType("DHTValue", Union[int, float, bool, str, bytes])
KadPeerTuple = Tuple[PeerIDBytes, IP, Port]
FindResponse = Union[Sequence[KadPeerTuple], Dict[str, DHTValue]]
