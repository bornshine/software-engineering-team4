(function (global) {
  'use strict';

  const Silkhollow = (global.Silkhollow = global.Silkhollow || {});
  const CFG = Silkhollow.CFG;
  const VIEW_W = Silkhollow.VIEW_W;
  const VIEW_H = Silkhollow.VIEW_H;

  class Camera {
    constructor(levelW, levelH) {
      this.x = 0;
      this.y = 0;
      this.renderX = 0;
      this.renderY = 0;
      this.levelW = levelW;
      this.levelH = levelH;
      this.shakeTime = 0;
      this.shakeMag = 0;
    }

    shake(mag, duration) {
      if (mag >= this.shakeMag || this.shakeTime <= 0) {
        this.shakeMag = mag;
        this.shakeTime = Math.max(this.shakeTime, duration);
      }
    }

    snap(targetX, targetY) {
      this.x = Silkhollow.clamp(targetX - VIEW_W * 0.5, 0, Math.max(0, this.levelW - VIEW_W));
      this.y = Silkhollow.clamp(targetY - VIEW_H * 0.52, 0, Math.max(0, this.levelH - VIEW_H));
      this.renderX = this.x;
      this.renderY = this.y;
    }

    update(dt, player, bossArena, bossActive) {
      let desiredX = player.cx + player.facing * 75 - VIEW_W * 0.5;
      let desiredY = player.cy - 28 - VIEW_H * 0.5;

      // 进入 Boss 战后镜头稳定构图于织渊王座竞技场
      if (bossActive && bossArena) {
        const arenaCenterX = (bossArena.minX + bossArena.maxX) * 0.5;
        desiredX = Silkhollow.lerp(desiredX, arenaCenterX - VIEW_W * 0.5, 0.55);
        desiredY = bossArena.floorY - VIEW_H + 110;
      }

      desiredX = Silkhollow.clamp(desiredX, 0, Math.max(0, this.levelW - VIEW_W));
      desiredY = Silkhollow.clamp(desiredY, 0, Math.max(0, this.levelH - VIEW_H));

      const smooth = 1 - Math.exp(-7.5 * dt);
      this.x = Silkhollow.lerp(this.x, desiredX, smooth);
      this.y = Silkhollow.lerp(this.y, desiredY, smooth);

      let sx = 0;
      let sy = 0;
      if (this.shakeTime > 0) {
        this.shakeTime -= dt;
        const decay = Math.max(0, this.shakeTime * 3.5);
        const amp = this.shakeMag * Math.min(1, decay);
        sx = (Math.random() * 2 - 1) * amp;
        sy = (Math.random() * 2 - 1) * amp;
      } else {
        this.shakeMag = 0;
      }
      this.renderX = this.x + sx;
      this.renderY = this.y + sy;
    }
  }

  class InputManager {
    constructor(canvas) {
      this.canvas = canvas;
      this.keys = new Set();
      this.justPressed = new Set();
      this.mouseLeftDown = false;
      this.mouseRightDown = false;
      this.mouseLeftPressed = false;
      this.mouseRightPressed = false;
      this.mouseX = VIEW_W * 0.5;
      this.mouseY = VIEW_H * 0.5;
      this.mouseMoveTimer = 0;

      this.bindEvents();
    }

    bindEvents() {
      global.addEventListener('keydown', (e) => {
        const code = e.code;
        if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Tab'].includes(code)) {
          e.preventDefault();
        }
        if (!this.keys.has(code)) {
          this.justPressed.add(code);
        }
        this.keys.add(code);
      });

      global.addEventListener('keyup', (e) => {
        this.keys.delete(e.code);
      });

      global.addEventListener('blur', () => {
        this.keys.clear();
        this.mouseLeftDown = false;
        this.mouseRightDown = false;
      });

      this.canvas.addEventListener('contextmenu', (e) => e.preventDefault());

      this.canvas.addEventListener('mousemove', (e) => {
        const rect = this.canvas.getBoundingClientRect();
        this.mouseX = ((e.clientX - rect.left) / rect.width) * VIEW_W;
        this.mouseY = ((e.clientY - rect.top) / rect.height) * VIEW_H;
        this.mouseMoveTimer = 3.5;
      });

      this.canvas.addEventListener('mousedown', (e) => {
        if (e.button === 0) {
          this.mouseLeftDown = true;
          this.mouseLeftPressed = true;
        } else if (e.button === 2) {
          this.mouseRightDown = true;
          this.mouseRightPressed = true;
          this.mouseMoveTimer = 3.5;
        }
      });

      global.addEventListener('mouseup', (e) => {
        if (e.button === 0) this.mouseLeftDown = false;
        if (e.button === 2) this.mouseRightDown = false;
      });
    }

    isDown(codes) {
      for (const c of codes) if (this.keys.has(c)) return true;
      return false;
    }

    wasPressed(codes) {
      for (const c of codes) if (this.justPressed.has(c)) return true;
      return false;
    }

    sample(dt) {
      if (this.mouseMoveTimer > 0) this.mouseMoveTimer -= dt;
      if (this.wasPressed(['KeyK', 'KeyE'])) {
        // 纯键盘按 K 时切回方向智能锁敌
        if (this.justPressed.has('KeyK')) this.mouseMoveTimer = 0;
      }

      const left = this.isDown(['KeyA', 'ArrowLeft']);
      const right = this.isDown(['KeyD', 'ArrowRight']);
      const up = this.isDown(['KeyW', 'ArrowUp']);
      const down = this.isDown(['KeyS', 'ArrowDown']);

      const state = {
        x: (right ? 1 : 0) - (left ? 1 : 0),
        y: (down ? 1 : 0) - (up ? 1 : 0),
        upPressed: this.wasPressed(['KeyW', 'ArrowUp']),
        jumpHeld: this.isDown(['Space', 'KeyZ']),
        jumpPressed: this.wasPressed(['Space', 'KeyZ']),
        attackPressed: this.mouseLeftPressed || this.wasPressed(['KeyJ', 'KeyX']),
        dashPressed: this.wasPressed(['ShiftLeft', 'ShiftRight', 'KeyL', 'KeyC']),
        grappleHeld: this.mouseRightDown || this.isDown(['KeyE', 'KeyK']),
        grapplePressed: this.mouseRightPressed || this.wasPressed(['KeyE', 'KeyK']),
        soulHeld: this.isDown(['KeyF', 'KeyQ', 'KeyV']),
        pausePressed: this.wasPressed(['Escape', 'KeyH']),
        mapPressed: this.wasPressed(['Tab']),
        mutePressed: this.wasPressed(['KeyM']),
        mouseX: this.mouseX,
        mouseY: this.mouseY,
        mouseRecentlyMoved: this.mouseMoveTimer > 0,
      };

      this.justPressed.clear();
      this.mouseLeftPressed = false;
      this.mouseRightPressed = false;
      return state;
    }
  }

  class Game {
    constructor() {
      this.canvas = document.getElementById('game-canvas');
      this.fullmapCanvas = document.getElementById('fullmap-canvas');
      this.ui = {
        title: document.getElementById('title-screen'),
        pause: document.getElementById('pause-screen'),
        map: document.getElementById('map-screen'),
        victory: document.getElementById('victory-screen'),
        topActions: document.getElementById('top-actions'),
        loreBanner: document.getElementById('lore-banner'),
        loreTitle: document.getElementById('lore-title'),
        loreText: document.getElementById('lore-text'),
        zoneBanner: document.getElementById('zone-banner'),
        zoneName: document.getElementById('zone-name'),
        zoneSub: document.getElementById('zone-sub'),
        btnMute: document.getElementById('btn-mute'),
        victoryStats: document.getElementById('victory-stats'),
      };

      this.audio = new Silkhollow.AudioEngine();
      this.input = new InputManager(this.canvas);
      this.renderer = new Silkhollow.Renderer(this.canvas);

      this.mode = 'title'; // title | playing | paused | map | victory
      this.hitstopTimer = 0;
      this.loreTimer = 0;
      this.lastZoneId = null;
      this.currentZone = Silkhollow.ZONES[0];
      this.accumulator = 0;
      this.lastFrameTime = 0;

      this.initWorld();
      this.bindUI();
      this.startLoop();
    }

    initWorld() {
      this.level = new Silkhollow.Level();
      this.player = new Silkhollow.Player(this.level.spawnPos.x, this.level.spawnPos.y);
      this.enemies = Silkhollow.createEnemiesFromLevel(this.level);
      this.enemyProjectiles = [];
      this.particles = new Silkhollow.ParticleSystem();
      this.camera = new Camera(this.level.width, this.level.height);
      this.camera.snap(this.player.cx, this.player.cy);

      this.stats = {
        playTime: 0,
        damageTaken: 0,
        enemiesDefeated: 0,
        deaths: 0,
      };
      this.bossDefeated = false;
      this.lastZoneId = null;
      this.currentZone = this.level.getZoneAt(this.player.cx, this.player.cy);
      this.level.markVisited(this.player.cx, this.player.cy);
    }

    bindUI() {
      document.getElementById('btn-start').addEventListener('click', () => {
        this.audio.init();
        this.setMode('playing');
        this.announceZone(this.currentZone);
      });
      document.getElementById('btn-title-controls').addEventListener('click', () => {
        this.audio.init();
        this.setMode('paused');
      });
      document.getElementById('btn-resume').addEventListener('click', () => this.setMode('playing'));
      document.getElementById('btn-pause').addEventListener('click', () => this.setMode('paused'));
      document.getElementById('btn-help').addEventListener('click', () => this.setMode('paused'));
      document.getElementById('btn-map').addEventListener('click', () => this.toggleMap());
      document.getElementById('btn-close-map').addEventListener('click', () => this.setMode('playing'));
      document.getElementById('btn-mute').addEventListener('click', () => this.toggleMute());

      document.getElementById('btn-respawn-bench').addEventListener('click', () => {
        this.onPlayerDeath(true);
        this.setMode('playing');
      });
      document.getElementById('btn-restart').addEventListener('click', () => {
        this.initWorld();
        this.audio.setBossMode(false);
        this.setMode('playing');
        this.announceZone(this.currentZone);
      });
      document.getElementById('btn-continue-explore').addEventListener('click', () => this.setMode('playing'));
      document.getElementById('btn-victory-restart').addEventListener('click', () => {
        this.initWorld();
        this.setMode('playing');
        this.announceZone(this.currentZone);
      });
    }

    setMode(newMode) {
      this.mode = newMode;
      this.ui.title.classList.toggle('hidden', newMode !== 'title');
      this.ui.pause.classList.toggle('hidden', newMode !== 'paused');
      this.ui.map.classList.toggle('hidden', newMode !== 'map');
      this.ui.victory.classList.toggle('hidden', newMode !== 'victory');
      this.ui.topActions.classList.toggle('hidden', newMode === 'title');

      if (newMode === 'map') {
        this.renderer.drawFullMap(this.fullmapCanvas, this);
      }
    }

    toggleMap() {
      if (this.mode === 'playing') this.setMode('map');
      else if (this.mode === 'map') this.setMode('playing');
    }

    toggleMute() {
      const muted = this.audio.toggleMute();
      this.ui.btnMute.textContent = muted ? '音效: 关' : '音效: 开';
    }

    triggerHitstop(duration) {
      this.hitstopTimer = Math.max(this.hitstopTimer, duration);
    }

    showLore(title, text, duration) {
      this.ui.loreTitle.textContent = title;
      this.ui.loreText.textContent = text;
      this.ui.loreBanner.classList.remove('hidden');
      this.loreTimer = duration || 3.2;
    }

    announceZone(zone) {
      if (!zone) return;
      this.ui.zoneName.textContent = zone.name;
      this.ui.zoneSub.textContent = zone.sub;
      this.ui.zoneBanner.classList.remove('hidden');
      // 触发 CSS 淡入淡出动画重启
      void this.ui.zoneBanner.offsetWidth;
      this.ui.zoneBanner.style.animation = 'none';
      void this.ui.zoneBanner.offsetWidth;
      this.ui.zoneBanner.style.animation = '';
    }

    onPlayerDeath(manual) {
      if (!manual) this.stats.deaths += 1;
      this.player.respawnAtBench();
      this.enemyProjectiles = [];
      this.audio.setBossMode(false);
      this.level.resetBossArenaState();
      // 复活所有常规敌怪与未击败的 Boss
      const fresh = Silkhollow.createEnemiesFromLevel(this.level);
      if (this.bossDefeated) {
        this.enemies = fresh.filter((e) => !e.isBoss);
      } else {
        this.enemies = fresh;
      }
      this.camera.snap(this.player.cx, this.player.cy);
      this.showLore('长椅苏醒', '苍白容器已在最近歇息的长椅处重塑。', 2.6);
    }

    onBossDefeated() {
      this.bossDefeated = true;
      const mins = Math.floor(this.stats.playTime / 60);
      const secs = Math.floor(this.stats.playTime % 60);
      const timeStr = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
      const secrets = (this.player.hasSilkWings ? 1 : 0) + (this.player.hasMaskShard ? 1 : 0);

      setTimeout(() => {
        this.ui.victoryStats.innerHTML = `
          <div class="stat-item"><div class="stat-label">通关用时</div><div class="stat-value">${timeStr}</div></div>
          <div class="stat-item"><div class="stat-label">承受伤害</div><div class="stat-value">${this.stats.damageTaken} 次</div></div>
          <div class="stat-item"><div class="stat-label">净化魔物 / 苍白微尘</div><div class="stat-value">${this.stats.enemiesDefeated} / ${this.player.shards}</div></div>
          <div class="stat-item"><div class="stat-label">核心遗物发现</div><div class="stat-value">${secrets} / 2</div></div>
        `;
        this.setMode('victory');
      }, 1450);
    }

    stepSimulation(dt) {
      const input = this.input.sample(dt);

      if (input.mutePressed) this.toggleMute();
      if (input.pausePressed && (this.mode === 'playing' || this.mode === 'paused')) {
        this.setMode(this.mode === 'playing' ? 'paused' : 'playing');
        return;
      }
      if (input.mapPressed && (this.mode === 'playing' || this.mode === 'map')) {
        this.toggleMap();
        return;
      }

      if (this.mode !== 'playing') {
        this.particles.update(dt);
        return;
      }

      this.stats.playTime += dt;
      this.audio.updateAmbient(dt, true);

      // 顿帧（Hitstop）期间冻结战斗模拟，仅保留相机微震增强打击感
      if (this.hitstopTimer > 0) {
        this.hitstopTimer -= dt;
        this.camera.update(dt, this.player, this.level.bossArena, false);
        return;
      }

      this.level.update(dt);
      this.player.update(dt, input, this);

      for (const e of this.enemies) {
        if (!e.dead) e.update(dt, this);
      }

      // 更新敌方投射物
      for (let i = this.enemyProjectiles.length - 1; i >= 0; i--) {
        const p = this.enemyProjectiles[i];
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        p.life -= dt;

        // 玩家骨钉可以劈散普通腐化孢子！
        const slashBox = this.player.getSlashBox();
        if (slashBox && !p.isSpear && p.x > slashBox.x && p.x < slashBox.x + slashBox.w && p.y > slashBox.y && p.y < slashBox.y + slashBox.h) {
          this.particles.burst(p.x, p.y, 10, Silkhollow.COLORS.corruptOrange, 160);
          this.audio.playClang();
          this.enemyProjectiles.splice(i, 1);
          continue;
        }

        const pr = { x: p.x - p.radius, y: p.y - p.radius, w: p.radius * 2, h: p.radius * 2 };
        if (Silkhollow.aabb(pr, this.player)) {
          this.player.takeDamage(1, p.x, this, false);
          this.enemyProjectiles.splice(i, 1);
          continue;
        }

        const tx = Math.floor(p.x / Silkhollow.TILE_SIZE);
        const ty = Math.floor(p.y / Silkhollow.TILE_SIZE);
        if (p.life <= 0 || this.level.isSolidTile(tx, ty)) {
          this.particles.burst(p.x, p.y, 6, p.color, 110);
          this.enemyProjectiles.splice(i, 1);
        }
      }

      // 长椅交互（靠近按 W / ↑ 歇息存档并回满血）
      for (const b of this.level.benches) {
        if (input.upPressed && Silkhollow.dist(this.player.cx, this.player.cy, b.x, b.y - 18) < 75) {
          b.lit = true;
          this.player.fullRestore(b);
          this.audio.playBenchRest();
          this.particles.ring(b.x, b.y - 24, Silkhollow.COLORS.silkBright, 95);
          this.particles.burst(b.x, b.y - 24, 24, Silkhollow.COLORS.paleWhite, 190);
          this.showLore(b.name, '生命已完全恢复，灵魂容器微光流转，已记录当前存档点。', 2.8);
        }
      }

      // 收集物拾取（苍白微尘 / 苍白丝翼 / 面具碎片）
      for (const p of this.level.pickups) {
        if (p.collected) continue;
        if (Silkhollow.dist(this.player.cx, this.player.cy, p.x, p.y) < 34) {
          p.collected = true;
          this.audio.playPickup();
          this.particles.burst(p.x, p.y, 24, Silkhollow.COLORS.silkBright, 260);
          this.particles.ring(p.x, p.y, Silkhollow.COLORS.paleWhite, 85);

          if (p.type === 'shard') {
            this.player.shards += 25;
          } else if (p.type === 'silk_wings') {
            this.player.hasSilkWings = true;
            this.player.canDoubleJump = true;
            this.triggerHitstop(0.12);
            this.camera.shake(6, 0.25);
            this.showLore(p.title, p.desc, 5.2);
          } else if (p.type === 'mask_shard') {
            this.player.hasMaskShard = true;
            this.player.maxHp += 1;
            this.player.hp = this.player.maxHp;
            this.triggerHitstop(0.12);
            this.camera.shake(6, 0.25);
            this.showLore(p.title, p.desc, 5.0);
          }
        }
      }

      // 靠近石碑自动显示教学与世界观碑文
      let nearTablet = null;
      for (const t of this.level.tablets) {
        if (Silkhollow.dist(this.player.cx, this.player.cy, t.x, t.y - 24) < 76) {
          nearTablet = t;
          break;
        }
      }
      if (this.loreTimer > 0) {
        this.loreTimer -= dt;
        if (this.loreTimer <= 0 && !nearTablet) {
          this.ui.loreBanner.classList.add('hidden');
        }
      } else if (nearTablet) {
        this.ui.loreTitle.textContent = nearTablet.title;
        this.ui.loreText.textContent = nearTablet.text;
        this.ui.loreBanner.classList.remove('hidden');
      } else {
        this.ui.loreBanner.classList.add('hidden');
      }

      // 探索迷雾更新 & 分区标题切换
      this.level.markVisited(this.player.cx, this.player.cy);
      const zone = this.level.getZoneAt(this.player.cx, this.player.cy);
      if (zone.id !== this.lastZoneId) {
        this.lastZoneId = zone.id;
        this.currentZone = zone;
        this.announceZone(zone);
      }

      const boss = this.enemies.find((e) => e.isBoss && e.active && !e.dead);
      this.camera.update(dt, this.player, this.level.bossArena, !!boss);
      this.particles.update(dt);
    }

    startLoop() {
      const tick = (now) => {
        if (!this.lastFrameTime) this.lastFrameTime = now;
        const frameDt = Math.min(0.05, (now - this.lastFrameTime) / 1000);
        this.lastFrameTime = now;
        this.accumulator += frameDt;

        while (this.accumulator >= CFG.FIXED_DT) {
          this.stepSimulation(CFG.FIXED_DT);
          this.accumulator -= CFG.FIXED_DT;
        }

        this.renderer.render(this, frameDt);
        global.requestAnimationFrame(tick);
      };
      global.requestAnimationFrame(tick);
    }
  }

  global.addEventListener('DOMContentLoaded', () => {
    global.__silkhollowGame = new Game();
  });
})(window);
