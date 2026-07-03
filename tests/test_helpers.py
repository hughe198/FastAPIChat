from unittest.mock import AsyncMock
from starlette.websockets import WebSocketState


class FakeWebSocket:
    """Minimal stand-in for a starlette WebSocket.

    Room and the message handlers only ever call `await
    websocket.send_json(...)`, `await websocket.close(...)`, and read
    `.client_state`, so that's all this needs to fake.
    """
    def __init__(self):
        self.client_state = WebSocketState.CONNECTED
        self.send_json = AsyncMock()
        self.close = AsyncMock()


def make_ws() -> FakeWebSocket:
    return FakeWebSocket()