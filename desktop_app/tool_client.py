import socket
import struct


class ShortToolResponseError(ValueError):
    pass


class ToolModbusClient:
    def __init__(self, timeout: float = 1.0):
        self.transaction_id = 0
        self.timeout = timeout

    def set_timeout(self, timeout: float):
        self.timeout = max(float(timeout), 0.1)

    def receive_exact(self, sock: socket.socket, size: int) -> bytes:
        chunks = []
        remaining = size
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ShortToolResponseError("设备响应中断")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def receive_modbus_response(self, sock: socket.socket) -> bytes:
        header = self.receive_exact(sock, 7)
        _, _, length = struct.unpack(">HHH", header[:6])
        if length <= 0:
            raise ShortToolResponseError("响应长度异常")
        body = self.receive_exact(sock, length - 1)
        return header + body

    def read_register(self, host: str, port: int, unit_id: int, register_address: int) -> int:
        if not host:
            raise ValueError("设备IP为空")

        self.transaction_id = (self.transaction_id + 1) % 65536
        request = struct.pack(
            ">HHHBBHH",
            self.transaction_id,
            0,
            6,
            unit_id,
            3,
            register_address,
            1,
        )
        with socket.create_connection((host, port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(request)
            response = self.receive_modbus_response(sock)

        if len(response) < 11:
            raise ShortToolResponseError("数据长度不足")
        transaction_id, protocol_id, _, response_unit, function_code = struct.unpack(">HHHBB", response[:8])
        if transaction_id != self.transaction_id or protocol_id != 0 or response_unit != unit_id:
            raise ValueError("报文头不匹配")
        if function_code & 0x80:
            raise ValueError(f"设备返回异常码 {response[8] if len(response) > 8 else ''}")
        if function_code != 3 or response[8] < 2:
            raise ValueError("不是读寄存器响应")
        return struct.unpack(">H", response[9:11])[0]

    def write_register(self, host: str, port: int, unit_id: int, register_address: int, value: int):
        if not host:
            raise ValueError("设备IP为空")

        self.transaction_id = (self.transaction_id + 1) % 65536
        request = struct.pack(
            ">HHHBBHH",
            self.transaction_id,
            0,
            6,
            unit_id,
            6,
            register_address,
            value,
        )
        with socket.create_connection((host, port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(request)
            response = self.receive_modbus_response(sock)

        if len(response) < 12:
            raise ShortToolResponseError("数据长度不足")
        transaction_id, protocol_id, _, response_unit, function_code = struct.unpack(">HHHBB", response[:8])
        if transaction_id != self.transaction_id or protocol_id != 0 or response_unit != unit_id:
            raise ValueError("报文头不匹配")
        if function_code & 0x80:
            raise ValueError(f"设备返回异常码 {response[8] if len(response) > 8 else ''}")
        if function_code != 6:
            raise ValueError("不是写寄存器响应")
