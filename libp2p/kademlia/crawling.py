from collections import Counter
import logging
from typing import Awaitable, Callable, Dict, List, Mapping, Sequence, Tuple

from libp2p.typing import (
    DHTValue,
    FindNodeResponse,
    FindValueResponse,
    FindXResponse,
    PeerIDBytes,
    RPCSuccessful,
)

from .kad_peerinfo import KadPeerHeap, KadPeerInfo, create_kad_peerinfo
from .protocol import KademliaProtocol
from .utils import gather_dict

log = logging.getLogger(__name__)

TRPCMethod = Callable[[KadPeerInfo, KadPeerInfo], Awaitable[Tuple[RPCSuccessful, FindXResponse]]]

TResponses = Mapping[PeerIDBytes, Tuple[RPCSuccessful, FindXResponse]]


class SpiderCrawl:
    """
    Crawl the network and look for given 160-bit keys.
    """

    protocol: KademliaProtocol
    ksize: int
    alpha: int
    node: KadPeerInfo
    nearest: KadPeerHeap
    last_ids_crawled: List[PeerIDBytes]

    def __init__(
        self,
        protocol: KademliaProtocol,
        node: KadPeerInfo,
        peers: Sequence[KadPeerInfo],
        ksize: int,
        alpha: int,
    ) -> None:
        """
        Create a new C{SpiderCrawl}er.

        Args:
            protocol: A :class:`~kademlia.protocol.KademliaProtocol` instance.
            node: A :class:`~kademlia.node.Node` representing the key we're
                  looking for
            peers: A list of :class:`~kademlia.node.Node` instances that
                   provide the entry point for the network
            ksize: The value for k based on the paper
            alpha: The value for alpha based on the paper
        """
        self.protocol = protocol
        self.ksize = ksize
        self.alpha = alpha
        self.node = node
        self.nearest = KadPeerHeap(self.node, self.ksize)
        self.last_ids_crawled = []
        log.info("creating spider with peers: %s", peers)
        self.nearest.push(peers)

    async def _find(self, rpcmethod: TRPCMethod) -> FindXResponse:
        """
        Get either a value or list of nodes.

        Args:
            rpcmethod: The protocol's callfindValue or call_find_node.

        The process:
          1. calls find_* to current ALPHA nearest not already queried nodes,
             adding results to current nearest list of k nodes.
          2. current nearest list needs to keep track of who has been queried
             already sort by nearest, keep KSIZE
          3. if list is same as last time, next call should be to everyone not
             yet queried
          4. repeat, unless nearest list has all been queried, then ur done
        """
        log.info("crawling network with nearest: %s", str(tuple(self.nearest)))
        count = self.alpha
        if self.nearest.get_ids() == self.last_ids_crawled:
            count = len(self.nearest)
        self.last_ids_crawled = self.nearest.get_ids()

        dicts = {}
        for peer in self.nearest.get_uncontacted()[:count]:
            dicts[peer.peer_id_bytes] = rpcmethod(peer, self.node)
            self.nearest.mark_contacted(peer)
        found: Dict[PeerIDBytes, Tuple[RPCSuccessful, FindXResponse]] = await gather_dict(dicts)
        return await self._nodes_found(found)

    async def _nodes_found(self, responses: TResponses) -> List[PeerIDBytes]:
        raise NotImplementedError


class ValueSpiderCrawl(SpiderCrawl):
    def __init__(
        self,
        protocol: KademliaProtocol,
        node: KadPeerInfo,
        peers: Sequence[KadPeerInfo],
        ksize: int,
        alpha: int,
    ):
        SpiderCrawl.__init__(self, protocol, node, peers, ksize, alpha)
        # keep track of the single nearest node without value - per
        # section 2.3 so we can set the key there if found
        self.nearest_without_value = KadPeerHeap(self.node, 1)

    async def find(self) -> DHTValue:
        """
        Find either the closest nodes or the value requested.
        """
        # ignore type: passing call_find_value here so the _find should return DHTValue
        return await self._find(self.protocol.call_find_value)  # type: ignore

    # ignore typing for the return since we are certain the return here
    async def _nodes_found(  # type: ignore
        self, responses: Mapping[PeerIDBytes, Tuple[RPCSuccessful, FindValueResponse]]
    ) -> DHTValue:
        """
        Handle the result of an iteration in _find.
        """
        toremove = []
        found_values = []
        for peerid, response in responses.items():
            rpc_response = RPCFindResponse(response)
            if not rpc_response.happened():
                toremove.append(peerid)
            elif rpc_response.has_value():
                found_values.append(rpc_response.get_value())
            else:
                peer = self.nearest.get_node(peerid)
                self.nearest_without_value.push(peer)
                self.nearest.push(rpc_response.get_node_list())
        self.nearest.remove(toremove)

        if found_values:
            return await self._handle_found_values(found_values)
        if self.nearest.have_contacted_all():
            # not found!
            return None
        return await self.find()

    async def _handle_found_values(self, values: Sequence[DHTValue]) -> DHTValue:
        """
        We got some values!  Exciting.  But let's make sure
        they're all the same or freak out a little bit.  Also,
        make sure we tell the nearest node that *didn't* have
        the value to store it.
        """
        value_counts = Counter(values)
        if len(value_counts) != 1:
            log.warning("Got multiple values for key %i: %s", self.node.xor_id, str(values))
        value = value_counts.most_common(1)[0][0]

        peer = self.nearest_without_value.popleft()
        if peer:
            await self.protocol.call_store(peer, self.node.peer_id_bytes, value)
        return value


class NodeSpiderCrawl(SpiderCrawl):
    async def find(self) -> FindNodeResponse:
        """
        Find the closest nodes.
        """
        return await self._find(self.protocol.call_find_node)

    async def _nodes_found(
        self, responses: Mapping[PeerIDBytes, Tuple[RPCSuccessful, FindNodeResponse]]
    ) -> FindNodeResponse:
        """
        Handle the result of an iteration in _find.
        """
        toremove = []
        for peerid, response in responses.items():
            rpc_response = RPCFindResponse(response)
            if not rpc_response.happened():
                toremove.append(peerid)
            else:
                self.nearest.push(rpc_response.get_node_list())
        self.nearest.remove(toremove)

        if self.nearest.have_contacted_all():
            return list(self.nearest)
        return await self.find()


class RPCFindResponse:
    response: Tuple[RPCSuccessful, FindXResponse]

    def __init__(self, response: Tuple[RPCSuccessful, FindXResponse]):
        """
        A wrapper for the result of a RPC find.

        Args:
            response: This will be a tuple of (<response received>, <value>)
                      where <value> will be a list of tuples if not found or
                      a dictionary of {'value': v} where v is the value desired
        """
        self.response = response

    def happened(self) -> RPCSuccessful:
        """
        Did the other host actually respond?
        """
        return self.response[0]

    def has_value(self) -> bool:
        return isinstance(self.response[1], dict)

    def get_value(self) -> DHTValue:
        # ignore typing since we assume __getitem__ is not an issue for reponse here
        return self.response[1]["value"]  # type: ignore

    def get_node_list(self) -> List[KadPeerInfo]:
        """
        Get the node list in the response.  If there's no value, this should
        be set.
        """
        nodelist = self.response[1] or []
        return [create_kad_peerinfo(*nodeple) for nodeple in nodelist]
