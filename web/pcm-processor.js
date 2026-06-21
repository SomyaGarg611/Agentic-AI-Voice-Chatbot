/**
 * AudioWorklet processor — converts float32 mic samples to Int16 PCM
 * and posts them to the main thread for WebSocket transmission.
 */
class PcmProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0][0];
    if (channel && channel.length > 0) {
      const pcm = new Int16Array(channel.length);
      for (let i = 0; i < channel.length; i++) {
        const s = Math.max(-1, Math.min(1, channel[i]));
        pcm[i] = s < 0 ? s * 32768 : s * 32767;
      }
      // Transfer the buffer (zero-copy)
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor('pcm-processor', PcmProcessor);
