import socket
import struct


class ShortToolResponseError(ValueError):
    pass


class ToolModbusClient:
    def __init__(self):
        self.transaction_id = 0

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
        with socket.create_connection((host, port), timeout=0.25) as sock:
            sock.settimeout(0.25)
            sock.sendall(request)
            response = sock.recv(1024)

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

