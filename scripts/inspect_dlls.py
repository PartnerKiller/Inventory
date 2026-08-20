import os
import struct

def inspect_imports(file_path):
    with open(file_path, "rb") as f:
        data = f.read()

    pe_offset = struct.unpack("<I", data[0x3C:0x40])[0]
    num_sections = struct.unpack("<H", data[pe_offset+6:pe_offset+8])[0]
    opt_header_size = struct.unpack("<H", data[pe_offset+20:pe_offset+22])[0]

    opt_offset = pe_offset + 24
    # Optional header data directories
    import_rva = struct.unpack("<I", data[opt_offset + 120 : opt_offset + 124])[0]
    import_size = struct.unpack("<I", data[opt_offset + 124 : opt_offset + 128])[0]

    print(f"Import Table RVA: 0x{import_rva:X} | Size: {import_size}")

    # Find section containing import_rva
    sec_offset = opt_offset + opt_header_size
    sec_found = None
    for i in range(num_sections):
        sec_data = data[sec_offset + i*40 : sec_offset + (i+1)*40]
        vsize, vaddr, rsize, raddr = struct.unpack("<IIII", sec_data[8:24])
        if vaddr <= import_rva < vaddr + vsize:
            sec_found = (vaddr, raddr)
            break

    if not sec_found:
        print("Could not map Import RVA to section.")
        return

    vaddr, raddr = sec_found
    import_file_offset = raddr + (import_rva - vaddr)

    # Read DLL names
    pos = import_file_offset
    dll_names = []
    while True:
        desc = data[pos : pos + 20]
        if len(desc) < 20 or desc == b"\x00" * 20:
            break
        orig_first_thunk, timedate, fchain, name_rva, first_thunk = struct.unpack("<IIIII", desc)
        if name_rva == 0:
            break
        name_file_offset = raddr + (name_rva - vaddr)
        name_end = data.find(b"\x00", name_file_offset)
        dll_name = data[name_file_offset:name_end].decode("ascii", errors="ignore")
        dll_names.append(dll_name)
        pos += 20

    print("Imported DLLs:")
    for d in dll_names:
        print(f"  - {d}")

if __name__ == "__main__":
    inspect_imports(r"D:\antigravity\Intentory Management Software\release\windows\AuraStock.exe")
