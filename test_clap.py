import sounddevice as sd
import numpy as np
import time

print("Bata palmas perto do microfone nos proximos 5 segundos...")
print("Vou mostrar o RMS maximo detectado a cada 100ms\n")

samplerate = 16000
chunk_size = 1024
chunks_per_second = samplerate // chunk_size

max_rms = 0
start = time.time()

def callback(indata, frames, time_info, status):
    global max_rms
    rms = np.sqrt(np.mean(indata**2))
    max_rms = max(max_rms, rms)
    if rms * 32768 > 100:  # so print se > 100
        print(f'  RMS: {rms*32768:.0f}  |  {"#" * int(rms*32768/200)}')

with sd.InputStream(samplerate=samplerate, channels=1, dtype='float32', 
                    blocksize=chunk_size, callback=callback):
    while time.time() - start < 5:
        sd.sleep(100)

print(f"\nRMS maximo detectado: {max_rms*32768:.0f}")
print(f"Threshold recomendado: {int(max_rms*32768*0.3)} a {int(max_rms*32768*0.5)}")