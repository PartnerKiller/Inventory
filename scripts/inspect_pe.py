import os
import struct
import hashlib

def inspect_binary(file_path):
    print(f"\n--- Inspecting: {file_path} ---")
    if not os.path.exists(file_path):
        print("File does not exist.")
        return

    size = os.path.getsize(file_path)
    with open(file_path, "rb") as f:
        data = f.read()

    sha256 = hashlib.sha256(data).hexdigest()
    print(f"Size: {size} bytes")
    print(f"SHA-256: {sha256}")

    if len(data) < 64:
        print("File too small to be a PE executable.")
        return

    # Check DOS header
    dos_sig = data[:2]
    if dos_sig != b"MZ":
        print("Invalid DOS signature (not MZ)")
        return
    
    pe_offset = struct.unpack("<I", data[0x3C:0x40])[0]
    if len(data) < pe_offset + 24:
        print("Truncated file before PE header.")
        return

    pe_sig = data[pe_offset:pe_offset+4]
    print(f"PE Signature at 0x{pe_offset:X}: {pe_sig}")

    machine = struct.unpack("<H", data[pe_offset+4:pe_offset+6])[0]
    num_sections = struct.unpack("<H", data[pe_offset+6:pe_offset+8])[0]
    opt_header_size = struct.unpack("<H", data[pe_offset+20:pe_offset+22])[0]
    characteristics = struct.unpack("<H", data[pe_offset+22:pe_offset+24])[0]

    machine_str = {0x8664: "AMD64 (x64)", 0x14C: "i386 (x86)", 0xAA64: "ARM64"}.get(machine, f"Unknown (0x{machine:X})")
    print(f"Machine Architecture: {machine_str}")
    print(f"Number of Sections: {num_sections}")
    print(f"Characteristics: 0x{characteristics:X}")

    opt_offset = pe_offset + 24
    if opt_header_size > 0:
        magic = struct.unpack("<H", data[opt_offset:opt_offset+2])[0]
        magic_str = {0x10B: "PE32 (32-bit)", 0x20B: "PE32+ (64-bit)"}.get(magic, f"Unknown (0x{magic:X})")
        print(f"Optional Header Magic: {magic_str}")

    # Read sections
    sec_offset = opt_offset + opt_header_size
    print("PE Sections:")
    for i in range(num_sections):
        sec_data = data[sec_offset + i*40 : sec_offset + (i+1)*40]
        if len(sec_data) < 40:
            break
        name = sec_data[:8].rstrip(b"\x00").decode("latin-1")
        vsize, vaddr, rsize, raddr = struct.unpack("<IIII", sec_data[8:24])
        print(f"  [{i+1}] {name:8s} | VirtualSize: {vsize:6d} | RawSize: {rsize:6d} | RawOffset: 0x{raddr:X}")

    # Check for CLR / .NET Header or Tauri / Rust signatures
    is_dotnet = b".text" in data and b"_CorExeMain" in data
    is_tauri = b"tauri" in data.lower() or b"tao" in data.lower() or b"wry" in data.lower()

    print(f"Contains .NET CLR runtime (_CorExeMain): {is_dotnet}")
    print(f"Contains Tauri/Rust native runtime signatures: {is_tauri}")

def main():
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "release", "windows"))
    inspect_binary(os.path.join(base, "AuraStock.exe"))
    inspect_binary(os.path.join(base, "AuraStock_1.1.0_x64-setup.exe"))
    inspect_binary(os.path.join(base, "AuraStock_1.1.0_x64_en-US.msi"))

if __name__ == "__main__":
    main()
