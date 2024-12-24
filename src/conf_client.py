import asyncio
import socket
import struct
from util import *
from config import *


class ConferenceClient:
    def __init__(self):
        self.is_working = True
        self.server_addr = (SERVER_IP, MAIN_SERVER_PORT)
        self.on_meeting = False
        self.conference_id = None
        self.conf_serve_port = None
        self.data_serve_ports = {}
        self.share_data = {}
        self.recv_tasks = []
        self.send_tasks = []
        # 连接服务器
        self.loop = asyncio.get_event_loop()
        self.received_chunks = {}


    async def create_conference(self):
        reader, writer = await asyncio.open_connection(*self.server_addr)
        writer.write('CREATE_CONFERENCE\n'.encode())
        await writer.drain()
        data = await reader.readline()
        message = data.decode().strip()
        if message.startswith('CREATE_OK'):
            _, conf_id, conf_port, data_ports = message.split(' ', 3)
            self.conference_id = int(conf_id)
            self.conf_serve_port = int(conf_port)
            self.data_serve_ports = eval(data_ports)
            self.on_meeting = True
            print(f'Conference {self.conference_id} created')
            await self.start_conference()
        else:
            print('Failed to create conference')
        writer.close()
        await writer.wait_closed()

    async def join_conference(self, conference_id):
        reader, writer = await asyncio.open_connection(*self.server_addr)
        writer.write(f'JOIN_CONFERENCE {conference_id}\n'.encode())
        await writer.drain()
        data = await reader.readline()
        message = data.decode().strip()
        if message.startswith('JOIN_OK'):
            _, conf_id, conf_port, data_ports = message.split(' ', 3)
            self.conference_id = int(conf_id)
            self.conf_serve_port = int(conf_port)
            self.data_serve_ports = eval(data_ports)
            self.on_meeting = True
            print(f'Joined conference {self.conference_id}')
            await self.start_conference()
        else:
            print('Failed to join conference')
        writer.close()
        await writer.wait_closed()

    async def quit_conference(self):
        self.on_meeting = False
        for task in self.recv_tasks + self.send_tasks:
            task.cancel()
        print('Quit conference')

    async def cancel_conference(self):
        if self.on_meeting:
            self.on_meeting = False
            # todo: cancle the conference on server side
            for task in self.recv_tasks + self.send_tasks:
                task.cancel()
            print('Conference canceled')
        else:
            print('No conference to cancel')



    async def keep_share(self, data_type, port, capture_function, compress=None, fps=1):
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)  # 64 KB buffer size
        # client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)  # 64 KB buffer size
        client_socket.sendto(b'Hello', (SERVER_IP, port))
        print(f'Start sharing {data_type} on port {port}')


        async def pack_chunk(chunk_index, total_chunks, chunk_data):
            # Use struct to pack chunk_index and total_chunks as unsigned integers (4 bytes each)
            # Then append the chunk_data (already in bytes)
            header = struct.pack('!II', chunk_index, total_chunks)  # '!II' means two unsigned integers in network byte order
            return header + chunk_data  # Concatenate header with chunk data

        try:
            while self.on_meeting:
                data = capture_function()
                print(self.on_meeting)
                if compress:
                    data = compress(data)

                # Split data into chunks
                data_chunks = [data[i:i + MAX_UDP_PACKET_SIZE] for i in range(0, len(data), MAX_UDP_PACKET_SIZE)]
                total_chunks = len(data_chunks)

                print(total_chunks)
                for i, chunk in enumerate(data_chunks):
                    # Add metadata to each chunk: (chunk_index, total_chunks)
                    print(i)
                    chunk_with_metadata = await pack_chunk(i, total_chunks, chunk)
                    client_socket.sendto(chunk_with_metadata, (SERVER_IP, port))
                print(f'Sent {data_type} on port {port}')

                await asyncio.sleep(1 / fps)

                print(2)
        except Exception as e:
            print(e)
        # except asyncio.CancelledError:
        #     pass
        finally:
            print(self.on_meeting)
            print(f'Stop sharing {data_type} on port {port}')
            client_socket.close()

    ## todo: implement this function
    def share_switch(self, data_type):
        '''
        switch for sharing certain type of data (screen, camera, audio, etc.)
        '''
        pass

    async def handle_received_chunk(self, data, data_type):
        # Extract metadata: chunk_index, total_chunks, chunk_data
        chunk_index, total_chunks, chunk_data = data

        if data_type not in self.received_chunks:
            self.received_chunks[data_type] = {}

        # Store the chunk data
        self.received_chunks[data_type][chunk_index] = chunk_data

        # Check if all chunks for this data_type have been received
        if len(self.received_chunks[data_type]) == total_chunks:
            # Reassemble the data by combining the chunks in order
            all_data = b''.join(self.received_chunks[data_type][i] for i in range(total_chunks))

            # Handle the reassembled data (e.g., process or store it)
            print(f'Reassembled data for {data_type}: {all_data}')

            # Clear the chunks for this data_type after reassembly
            del self.received_chunks[data_type]

    async def keep_recv(self, data_type, port, decompress=None):
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print(f'Start receiving {data_type} on port {port}')
        # client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)  # 64 KB buffer size
        # client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)  # 64 KB buffer size
        client_socket.sendto(b'Hello', (SERVER_IP, port))
        try:
            while self.on_meeting:
                # print(f'Receiving {data_type} on port {port}')
                data = bytearray()
                while True:
                    chunk, _ = client_socket.recvfrom(65536)
                    await self.handle_received_chunk(chunk, data_type)
                    print(chunk)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(chunk) < 1301072:
                        break
                if decompress:
                    data = decompress(data)
                self.share_data[data_type] = data
        except asyncio.CancelledError:
            pass
        finally:
            print(f'Stop receiving {data_type} on port {port}')
            client_socket.close()

    async def output_data(self):
        while self.on_meeting:
            # print('Output data: ', self.share_data.keys())
            # 显示接收到的数据
            if 'screen' in self.share_data:
                screen_image = self.share_data['screen']
            else:
                screen_image = None
            if 'camera' in self.share_data:
                camera_images = [self.share_data['camera']]
            else:
                camera_images = None
            display_image = overlay_camera_images(screen_image, camera_images)
            if display_image:
                img_array = np.array(display_image)
                cv2.imshow('Conference', cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR))
                cv2.waitKey(1)
            else:
                ## todo: 显示黑框
                pass

            # 播放接收到的音频
            if 'audio' in self.share_data:
                audio_data = self.share_data['audio']
                play_audio(audio_data)
            await asyncio.sleep(0.05)

    async def start_conference(self):
        # 启动数据接收和发送任务
        for data_type, port in self.data_serve_ports.items():
            if data_type in ['screen', 'camera']:
                print(f'Start sharing {data_type} on port {port}')
                send_task = asyncio.create_task(self.keep_share(
                    data_type, port,
                    capture_function=capture_screen if data_type == 'screen' else capture_camera,
                    compress=compress_image))
                recv_task = asyncio.create_task(self.keep_recv(
                    data_type, port, decompress=decompress_image))
            elif data_type == 'audio':
                send_task = asyncio.create_task(self.keep_share(
                    data_type, port, capture_function=capture_voice))
                recv_task = asyncio.create_task(self.keep_recv(
                    data_type, port))
            self.send_tasks.append(send_task)
            self.recv_tasks.append(recv_task)

        # 启动输出任务
        output_task = asyncio.create_task(self.output_data())
        self.recv_tasks.append(output_task)

        tasks = self.recv_tasks + self.send_tasks
        await asyncio.gather(*tasks)


    async def start(self):
        while True:
            if not self.on_meeting:
                status = 'Free'
            else:
                status = f'OnMeeting-{self.conference_id}'

            recognized = True
            cmd_input = input(f'({status}) Please enter a operation (enter "?" to help): ').strip().lower()
            fields = cmd_input.split(maxsplit=1)
            if len(fields) == 1:
                if cmd_input in ('?', '？'):
                    print(HELP)
                elif cmd_input == 'create':
                    await self.create_conference()
                elif cmd_input == 'quit':
                    await self.quit_conference()
                elif cmd_input == 'cancel':
                    await self.cancel_conference()
                else:
                    recognized = False
            elif len(fields) == 2:
                if fields[0] == 'join':
                    input_conf_id = fields[1]
                    if input_conf_id.isdigit():
                        await self.join_conference(int(input_conf_id))
                    else:
                        print('[Warn]: Input conference ID must be in digital form')
                else:
                    recognized = False
            else:
                recognized = False

            if not recognized:
                print(f'[Warn]: Unrecognized cmd_input {cmd_input}')


if __name__ == '__main__':
    client = ConferenceClient()
    asyncio.run(client.start())