import sounddevice as sd
import numpy as np

print('Dispositivos de audio:')
for i, dev in enumerate(sd.query_devices()):
    if dev['max_input_channels'] > 0:
        print(f'  [{i}] {dev["name"]} - {dev["max_input_channels"]} canais - {dev["default_samplerate"]}Hz')

print('\nTestando captura de 1 segundo...')
try:
    recording = sd.rec(int(16000 * 1), samplerate=16000, channels=1, dtype='float32')
    sd.wait()
    rms = np.sqrt(np.mean(recording**2))
    print(f'RMS capturado: {rms:.6f} ({rms*32768:.0f} em escala 16-bit)')
    if rms > 0.001:
        print('Microfone OK!')
    else:
        print('AVISO: RMS muito baixo - microfone pode estar mudo ou com ganho baixo')
except Exception as e:
    print(f'ERRO: {e}')