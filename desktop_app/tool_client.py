import logging
import socket
import struct
from typing import List, Optional


class ShortToolResponseError(ValueError):
    pass


class ToolModbusClient:
    def __init__(
        self,
        host: str = "",
        port: int = 502,
        unit_id: int = 1,
        timeout: float = 1.0,
    ):
        self.host = host
        self.port = int(port)
        self.unit_id = int(unit_id)
        self.timeout = max(float(timeout), 0.1)
        self.transaction_id = 0
        self.sock: Optional[socket.socket] = None
        self.connected = False

    def set_timeout(self, timeout: float):
        self.timeout = max(float(timeout), 0.1)
        if self.sock is not None:
            self.sock.settimeout(self.timeout)

    def connect(self):
        if self.is_connected():
            return
        if not self.host:
            raise ValueError("设备IP为空")
        self.disconnect()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            sock.settimeout(self.timeout)
            self.sock = sock
            self.connected = True
            logging.info("螺钉枪长连接建立成功：%s:%s", self.host, self.port)
        except (socket.timeout, ConnectionRefusedError, OSError, ValueError):
            self.disconnect()
            raise

    def disconnect(self):
        sock = self.sock
        was_connected = self.connected or sock is not None
        self.sock = None
        self.connected = False
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if was_connected:
            logging.info("螺钉枪长连接断开，socket已关闭")

    def is_connected(self) -> bool:
        return self.connected and self.sock is not None

    def ensure_connected(self):
        if not self.is_connected():
            self.connect()

    def receive_exact(self, size: int) -> bytes:
        if self.sock is None:
            raise ConnectionError("螺钉枪未连接")
        chunks = []
        remaining = size
        while remaining > 0:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise ShortToolResponseError("设备响应中断")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def receive_modbus_response(self) -> bytes:
        header = self.receive_exact(7)
        _, _, length = struct.unpack(">HHH", header[:6])
        if length < 2:
            raise ShortToolResponseError("响应长度异常")
        body = self.receive_exact(length - 1)
        return header + body

    def _request(self, function_code: int, register_address: int, value_or_count: int) -> bytes:
        self.ensure_connected()
        self.transaction_id = (self.transaction_id + 1) % 65536
        request = struct.pack(
            ">HHHBBHH",
            self.transaction_id,
            0,
            6,
            self.unit_id,
            function_code,
            register_address,
            value_or_count,
        )
        try:
            if self.sock is None:
                raise ConnectionError("螺钉枪未连接")
            self.sock.sendall(request)
            response = self.receive_modbus_response()
            if len(response) < 9:
                raise ShortToolResponseError("数据长度不足")
            transaction_id, protocol_id, _, response_unit, response_function = struct.unpack(
                ">HHHBB", response[:8]
            )
            if (
                transaction_id != self.transaction_id
                or protocol_id != 0
                or response_unit != self.unit_id
            ):
                raise ValueError("报文头不匹配")
            if response_function & 0x80:
                raise ValueError(f"设备返回异常码 {response[8]}")
            if response_function != function_code:
                raise ValueError("响应功能码不匹配")
            return response
        except (socket.timeout, ConnectionRefusedError, OSError, ValueError):
            self.disconnect()
            raise

    def read_register(self, register_address: int) -> int:
        return self.read_registers(register_address, 1)[0]

    def read_registers(self, register_address: int, count: int) -> List[int]:
        if count < 1 or count > 125:
            raise ValueError("读取寄存器数量必须在1到125之间")
        response = self._request(3, register_address, count)
        byte_count = response[8]
        expected_bytes = count * 2
        if byte_count != expected_bytes or len(response) < 9 + expected_bytes:
            self.disconnect()
            raise ShortToolResponseError("数据长度不足")
        return list(struct.unpack(f">{count}H", response[9 : 9 + expected_bytes]))

    def write_register(self, register_address: int, value: int):
        response = self._request(6, register_address, value)
        if len(response) < 12:
            self.disconnect()
            raise ShortToolResponseError("数据长度不足")
        echoed_address, echoed_value = struct.unpack(">HH", response[8:12])
        if echoed_address != register_address or echoed_value != value:
            self.disconnect()
            raise ValueError("写寄存器响应不匹配")
