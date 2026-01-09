import os
import math

class Chunker:
    """Handles splitting large files into chunks and reassembling them."""

    @staticmethod
    def split_file(file_path, chunk_size, output_dir):
        """
        Splits a file into multiple chunks using buffered IO to save RAM.
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        file_size = os.path.getsize(file_path)
        num_chunks = math.ceil(file_size / chunk_size)
        chunk_paths = []

        filename = os.path.basename(file_path)
        buffer_size = 1024 * 1024 # 1MB buffer

        with open(file_path, 'rb') as f:
            for i in range(num_chunks):
                chunk_name = f"{filename}.part{i}"
                chunk_path = os.path.join(output_dir, chunk_name)
                
                with open(chunk_path, 'wb') as chunk_file:
                    bytes_remaining = chunk_size
                    while bytes_remaining > 0:
                        read_size = min(buffer_size, bytes_remaining)
                        data = f.read(read_size)
                        if not data:
                            break
                        chunk_file.write(data)
                        bytes_remaining -= len(data)
                
                chunk_paths.append(chunk_path)
        
        return chunk_paths

    @staticmethod
    def merge_chunks(chunk_paths, output_path):
        """
        Merges multiple chunks into a single file using buffered IO.
        """
        buffer_size = 1024 * 1024 # 1MB buffer
        
        with open(output_path, 'wb') as output_file:
            for chunk_path in chunk_paths:
                if not os.path.exists(chunk_path):
                    raise FileNotFoundError(f"Chunk missing: {chunk_path}")
                
                with open(chunk_path, 'rb') as chunk_file:
                    while True:
                        data = chunk_file.read(buffer_size)
                        if not data:
                            break
                        output_file.write(data)
        
        return output_path
