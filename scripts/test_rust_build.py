import os
import subprocess
import shutil

def test_rust():
    cargo_bin = r"C:\Users\sayan\.cargo\bin"
    os.environ["PATH"] = cargo_bin + os.pathsep + os.environ["PATH"]

    rustc_path = shutil.which("rustc")
    cargo_path = shutil.which("cargo")
    print(f"Rustc: {rustc_path}")
    print(f"Cargo: {cargo_path}")

    # Compile small test
    with open("test_hello.rs", "w") as f:
        f.write('fn main() { println!("RUST COMPILER OK"); }\n')

    res = subprocess.run(["rustc", "test_hello.rs"], capture_output=True, text=True)
    print("Rustc compile return code:", res.returncode)
    if res.returncode == 0:
        run_res = subprocess.run([os.path.abspath("test_hello.exe")], capture_output=True, text=True)
        print("Run test output:", run_res.stdout.strip())
        for f in ["test_hello.rs", "test_hello.exe", "test_hello.pdb"]:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass
    else:
        print("Compile stderr:\n", res.stderr)

if __name__ == "__main__":
    test_rust()
