// Runs on the audio rendering thread: mixes every input channel down to mono
// and hands each 128-frame block to the main thread. Nothing is stored here.
class EchoPcmProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || input[0].length === 0) return true;

    const frames = input[0].length;
    const mono = new Float32Array(frames);
    for (let c = 0; c < input.length; c++) {
      const channel = input[c];
      for (let i = 0; i < frames; i++) mono[i] += channel[i];
    }
    if (input.length > 1) {
      for (let i = 0; i < frames; i++) mono[i] /= input.length;
    }
    this.port.postMessage(mono, [mono.buffer]);
    return true;
  }
}

registerProcessor("echo-pcm-processor", EchoPcmProcessor);
