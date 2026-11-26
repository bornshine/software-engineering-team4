(function (global) {
  'use strict';

  const Silkhollow = (global.Silkhollow = global.Silkhollow || {});

  class AudioEngine {
    constructor() {
      this.ctx = null;
      this.muted = false;
      this.bossMode = false;
      this.ambientTimer = 0;
      this.noteIndex = 0;
      this.masterGain = null;
      this.droneOsc = null;
      this.droneGain = null;
    }

    init() {
      if (this.ctx) {
        if (this.ctx.state === 'suspended') this.ctx.resume().catch(() => {});
        return;
      }
      const AC = global.AudioContext || global.webkitAudioContext;
      if (!AC) return;
      try {
        this.ctx = new AC();
        this.masterGain = this.ctx.createGain();
        this.masterGain.gain.value = this.muted ? 0 : 0.42;
        this.masterGain.connect(this.ctx.destination);
        this.startDrone();
      } catch (e) {
        this.ctx = null;
      }
    }

    toggleMute() {
      this.muted = !this.muted;
      if (this.masterGain && this.ctx) {
        this.masterGain.gain.setTargetAtTime(this.muted ? 0 : 0.42, this.ctx.currentTime, 0.04);
      }
      return this.muted;
    }

    setBossMode(active) {
      this.bossMode = active;
    }

    startDrone() {
      if (!this.ctx || !this.masterGain) return;
      const osc = this.ctx.createOscillator();
      const filter = this.ctx.createBiquadFilter();
      const gain = this.ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.value = 55; // A1 深邃洞窟基底
      filter.type = 'lowpass';
      filter.frequency.value = 140;
      gain.gain.value = 0.08;
      osc.connect(filter);
      filter.connect(gain);
      gain.connect(this.masterGain);
      osc.start();
      this.droneOsc = osc;
      this.droneGain = gain;
    }

    updateAmbient(dt, isPlaying) {
      if (!this.ctx || this.muted || !isPlaying) return;
      this.ambientTimer -= dt;
      if (this.ambientTimer <= 0) {
        if (this.bossMode) {
          // 紧张低沉 Boss 脉动音符（D小调）
          const bossNotes = [146.83, 174.61, 164.81, 130.81, 146.83, 220.0];
          const freq = bossNotes[this.noteIndex % bossNotes.length];
          this.noteIndex++;
          this.tone(freq, 'sawtooth', 0.28, 0.055, freq * 0.98, 420);
          this.ambientTimer = 0.52;
        } else {
          // 忧郁空灵地下五声铃音（A小调五声音阶）
          const notes = [440, 523.25, 659.25, 783.99, 587.33, 392.0, 523.25];
          const freq = notes[this.noteIndex % notes.length];
          this.noteIndex += (Math.random() < 0.6 ? 1 : 2);
          this.tone(freq, 'sine', 1.9, 0.045, freq, 1800);
          this.tone(freq * 2, 'sine', 1.1, 0.015, freq * 2, 2400);
          this.ambientTimer = 2.1 + Math.random() * 1.6;
        }
      }
    }

    tone(freq, type, duration, vol, endFreq, lpFreq) {
      if (!this.ctx || !this.masterGain || this.muted) return;
      const now = this.ctx.currentTime;
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq, now);
      if (endFreq && endFreq !== freq) {
        osc.frequency.exponentialRampToValueAtTime(Math.max(20, endFreq), now + duration);
      }
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.linearRampToValueAtTime(vol, now + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

      if (lpFreq) {
        const filter = this.ctx.createBiquadFilter();
        filter.type = 'lowpass';
        filter.frequency.value = lpFreq;
        osc.connect(filter);
        filter.connect(gain);
      } else {
        osc.connect(gain);
      }
      gain.connect(this.masterGain);
      osc.start(now);
      osc.stop(now + duration + 0.02);
    }

    noise(duration, vol, filterFreq, filterType) {
      if (!this.ctx || !this.masterGain || this.muted) return;
      const now = this.ctx.currentTime;
      const len = Math.max(1, Math.floor(this.ctx.sampleRate * duration));
      const buffer = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;

      const src = this.ctx.createBufferSource();
      src.buffer = buffer;

      const filter = this.ctx.createBiquadFilter();
      filter.type = filterType || 'bandpass';
      filter.frequency.value = filterFreq || 1200;

      const gain = this.ctx.createGain();
      gain.gain.setValueAtTime(vol, now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);

      src.connect(filter);
      filter.connect(gain);
      gain.connect(this.masterGain);
      src.start(now);
      src.stop(now + duration + 0.02);
    }

    playJump(isDouble) {
      if (isDouble) {
        this.tone(360, 'sine', 0.18, 0.16, 780);
        this.tone(720, 'triangle', 0.15, 0.09, 1180);
      } else {
        this.tone(210, 'sine', 0.14, 0.14, 460);
      }
    }

    playLand() {
      this.tone(110, 'triangle', 0.07, 0.12, 52);
      this.noise(0.05, 0.06, 480, 'lowpass');
    }

    playDash() {
      this.noise(0.16, 0.22, 1400, 'bandpass');
      this.tone(340, 'sawtooth', 0.14, 0.08, 120, 700);
    }

    playNailSwing(empowered) {
      this.noise(0.11, empowered ? 0.26 : 0.18, empowered ? 2600 : 1900, 'highpass');
      if (empowered) {
        this.tone(680, 'sine', 0.18, 0.14, 1320);
      }
    }

    playNailHit(isCrit) {
      this.tone(isCrit ? 190 : 150, 'sawtooth', 0.12, isCrit ? 0.28 : 0.2, 55, 650);
      this.noise(0.08, 0.2, 950, 'bandpass');
      if (isCrit) {
        this.tone(880, 'sine', 0.2, 0.15, 1320);
      }
    }

    playClang() {
      this.tone(1180, 'sine', 0.22, 0.2, 1120);
      this.tone(1790, 'triangle', 0.18, 0.14, 1650);
    }

    playSilkShoot() {
      this.tone(620, 'triangle', 0.11, 0.15, 1520);
      this.noise(0.08, 0.11, 3200, 'highpass');
    }

    playSilkLatch() {
      this.tone(920, 'sine', 0.16, 0.16, 1380);
      this.tone(1380, 'sine', 0.14, 0.09, 1760);
    }

    playSlingshot() {
      this.tone(523.25, 'sine', 0.18, 0.14, 783.99);
      this.tone(783.99, 'triangle', 0.22, 0.11, 1046.5);
    }

    playBellChime() {
      this.tone(293.66, 'sine', 1.6, 0.24, 290);
      this.tone(587.33, 'sine', 1.2, 0.14, 584);
      this.tone(880.0, 'triangle', 0.8, 0.09, 872);
    }

    playFocusHum() {
      this.tone(240, 'sine', 0.45, 0.09, 320);
    }

    playHealComplete() {
      this.tone(523.25, 'sine', 0.36, 0.18, 659.25);
      this.tone(783.99, 'sine', 0.48, 0.15, 1046.5);
    }

    playSoulCast() {
      this.tone(420, 'sawtooth', 0.22, 0.18, 160, 1100);
      this.noise(0.16, 0.18, 1600, 'bandpass');
    }

    playPlayerHurt() {
      this.tone(140, 'sawtooth', 0.26, 0.3, 48, 520);
      this.noise(0.18, 0.25, 600, 'lowpass');
    }

    playEnemyDeath() {
      this.tone(220, 'sawtooth', 0.22, 0.16, 62, 700);
      this.noise(0.14, 0.16, 900, 'bandpass');
    }

    playBenchRest() {
      this.tone(392.0, 'sine', 0.45, 0.14, 392);
      this.tone(587.33, 'sine', 0.65, 0.12, 587.33);
      this.tone(783.99, 'sine', 0.85, 0.1, 783.99);
    }

    playPickup() {
      this.tone(587.33, 'sine', 0.24, 0.16, 880);
      this.tone(880, 'triangle', 0.38, 0.14, 1174.66);
    }

    playBossRoar() {
      this.tone(115, 'sawtooth', 0.65, 0.25, 62, 380);
      this.tone(175, 'sawtooth', 0.55, 0.15, 92, 520);
      this.noise(0.45, 0.18, 420, 'lowpass');
    }

    playSlam() {
      this.tone(92, 'sine', 0.34, 0.32, 32);
      this.noise(0.24, 0.28, 350, 'lowpass');
    }

    playSilkExecution() {
      this.tone(330, 'sawtooth', 0.24, 0.25, 880, 1600);
      this.tone(880, 'sine', 0.42, 0.22, 1320);
      this.tone(110, 'sine', 0.32, 0.28, 42);
    }

    playBossDeath() {
      this.tone(220, 'sawtooth', 0.9, 0.26, 44, 520);
      this.tone(523.25, 'sine', 1.4, 0.18, 1046.5);
      this.noise(0.6, 0.24, 650, 'lowpass');
    }
  }

  Silkhollow.AudioEngine = AudioEngine;
})(window);
