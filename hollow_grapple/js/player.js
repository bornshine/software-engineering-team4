(function (global) {
  'use strict';

  const Silkhollow = (global.Silkhollow = global.Silkhollow || {});
  const CFG = Silkhollow.CFG;
  const TILE = Silkhollow.TILE;
  const TS = Silkhollow.TILE_SIZE;

  class Player {
    constructor(x, y) {
      this.x = x;
      this.y = y;
      this.w = CFG.PLAYER_W;
      this.h = CFG.PLAYER_H;
      this.vx = 0;
      this.vy = 0;
      this.facing = 1; // 1 右, -1 左

      // 状态标志
      this.onGround = false;
      this.wallDir = 0; // -1 贴左墙, 1 贴右墙
      this.wallSlide = false;
      this.coyoteTimer = 0;
      this.jumpBufferTimer = 0;
      this.wallJumpLockTimer = 0;
      this.dropThroughTimer = 0;

      // 能力与资源
      this.maxHp = CFG.START_MAX_HP;
      this.hp = this.maxHp;
      this.soul = 33; // 初始赠送一格灵魂，方便体验技能
      this.shards = 0;
      this.hasSilkWings = false; // 遗物：二段跳 + 延长钩锁射程
      this.hasMaskShard = false;

      // 空中资源
      this.canDoubleJump = false;
      this.canDash = true;
      this.dashTimer = 0;
      this.dashCooldown = 0;
      this.dashDir = 1;
      this.afterimages = [];

      // 战斗与下劈
      this.nailCooldown = 0;
      this.slash = null; // { dir, timer, duration, empowered, hitIds: Set }
      this.hookEmpowerTimer = 0;
      this.pogoRecoilTimer = 0;
      this.invulnTimer = 0;
      this.grappleInvuln = 0;
      this.hurtFlash = 0;

      // 灵魂凝聚 / 脉冲弹
      this.soulHoldTime = 0;
      this.isFocusing = false;
      this.focusProgress = 0;
      this.soulCastCooldown = 0;
      this.soulBolts = [];

      // 渊丝钩锁核心状态机
      this.grappleCooldown = 0;
      this.bestTarget = null;
      this.grapple = {
        state: 'idle', // idle | shooting | latched | zip | swing | enemy_zip | bell_pull
        tipX: 0,
        tipY: 0,
        anchorX: 0,
        anchorY: 0,
        target: null,
        targetType: null, // anchor | enemy | bell
        holdTime: 0,
        timer: 0,
        ropeLen: 150,
        waveAmp: 0,
        releasedEarly: false,
      };

      // 安全点与存档点
      this.lastSafeX = x;
      this.lastSafeY = y;
      this.benchX = x;
      this.benchY = y;
      this.benchId = 'bench_sanctuary';

      // 动画与布料披风 (Verlet 6节点)
      this.animTime = 0;
      this.squashX = 1;
      this.squashY = 1;
      this.cloak = [];
      for (let i = 0; i < 6; i++) {
        this.cloak.push({ x: x + this.w / 2, y: y + 14 + i * 5, ox: x + this.w / 2, oy: y + 14 + i * 5 });
      }
      this.healBurstTimer = 0;
    }

    get cx() { return this.x + this.w * 0.5; }
    get cy() { return this.y + this.h * 0.5; }
    get grappleRange() {
      return this.hasSilkWings ? CFG.GRAPPLE_RANGE_UPGRADED : CFG.GRAPPLE_RANGE_BASE;
    }

    resetAirResources() {
      this.canDash = true;
      this.canDoubleJump = this.hasSilkWings;
      this.grappleCooldown = Math.min(this.grappleCooldown, 0.08);
    }

    fullRestore(bench) {
      this.hp = this.maxHp;
      this.soul = Math.max(this.soul, 33);
      if (bench) {
        this.benchX = bench.x - this.w * 0.5;
        this.benchY = bench.y - this.h;
        this.benchId = bench.id;
      }
      this.lastSafeX = this.x;
      this.lastSafeY = this.y;
      this.healBurstTimer = 0.6;
    }

    respawnAtBench() {
      this.x = this.benchX;
      this.y = this.benchY;
      this.vx = 0;
      this.vy = 0;
      this.hp = this.maxHp;
      this.soul = 33;
      this.invulnTimer = 1.0;
      this.cancelGrapple(false);
      this.dashTimer = 0;
      this.isFocusing = false;
      this.focusProgress = 0;
      this.resetCloak();
    }

    resetCloak() {
      for (let i = 0; i < this.cloak.length; i++) {
        this.cloak[i].x = this.cx;
        this.cloak[i].y = this.y + 14 + i * 5;
        this.cloak[i].ox = this.cloak[i].x;
        this.cloak[i].oy = this.cloak[i].y;
      }
    }

    cancelGrapple(refreshAir) {
      if (this.grapple.state !== 'idle') {
        this.grapple.state = 'idle';
        this.grapple.target = null;
        this.grapple.targetType = null;
        if (refreshAir) {
          this.resetAirResources();
          this.grappleCooldown = 0.14;
        } else {
          this.grappleCooldown = CFG.GRAPPLE_COOLDOWN;
        }
      }
    }

    update(dt, input, world) {
      const { level, enemies, particles, audio, camera } = world;
      this.animTime += dt;

      // 冷却与计时器衰减
      if (this.coyoteTimer > 0) this.coyoteTimer -= dt;
      if (this.jumpBufferTimer > 0) this.jumpBufferTimer -= dt;
      if (this.wallJumpLockTimer > 0) this.wallJumpLockTimer -= dt;
      if (this.dropThroughTimer > 0) this.dropThroughTimer -= dt;
      if (this.dashCooldown > 0) this.dashCooldown -= dt;
      if (this.nailCooldown > 0) this.nailCooldown -= dt;
      if (this.hookEmpowerTimer > 0) this.hookEmpowerTimer -= dt;
      if (this.invulnTimer > 0) this.invulnTimer -= dt;
      if (this.grappleInvuln > 0) this.grappleInvuln -= dt;
      if (this.hurtFlash > 0) this.hurtFlash -= dt;
      if (this.grappleCooldown > 0) this.grappleCooldown -= dt;
      if (this.soulCastCooldown > 0) this.soulCastCooldown -= dt;
      if (this.healBurstTimer > 0) this.healBurstTimer -= dt;

      // 弹性挤压恢复
      this.squashX = Silkhollow.lerp(this.squashX, 1, Math.min(1, dt * 16));
      this.squashY = Silkhollow.lerp(this.squashY, 1, Math.min(1, dt * 16));

      if (input.jumpPressed) {
        this.jumpBufferTimer = CFG.JUMP_BUFFER;
      }

      // 扫描最佳钩锁目标（供 UI 准星与触发使用）
      this.scanGrappleTarget(level, enemies, input, camera);

      // 1. 处理灵魂凝聚 / 脉冲弹
      this.updateSoulSystem(dt, input, world);

      // 2. 处理钩锁触发与状态机
      if (input.grapplePressed && this.grapple.state === 'idle' && this.grappleCooldown <= 0 && this.bestTarget) {
        this.startGrapple(this.bestTarget, input, world);
      }

      // 3. 根据当前核心运动状态分支执行
      if (this.grapple.state !== 'idle') {
        this.updateGrappleState(dt, input, world);
      } else if (this.dashTimer > 0) {
        this.updateDash(dt, world);
      } else {
        this.updateStandardMovement(dt, input, world);
      }

      // 4. 骨钉四向劈砍与下劈弹反判定
      if (input.attackPressed && this.nailCooldown <= 0 && !this.isFocusing) {
        this.startSlash(input, world);
      }
      if (this.slash) {
        this.updateSlash(dt, world);
      }

      // 5. 更新灵魂脉冲弹与残影
      this.updateSoulBolts(dt, world);
      for (let i = this.afterimages.length - 1; i >= 0; i--) {
        this.afterimages[i].alpha -= dt * 4.2;
        if (this.afterimages[i].alpha <= 0) this.afterimages.splice(i, 1);
      }

      // 6. 尖刺碰撞检测
      this.checkHazardSpikes(world);

      // 7. 柔性布料披风更新
      this.updateCloak(dt);
    }

    scanGrappleTarget(level, enemies, input, camera) {
      const range = this.grappleRange;
      const cx = this.cx;
      const cy = this.cy;
      const candidates = [];

      // 1) 渊丝环锚点（高优先级，确保跑酷摆荡不误锁脚边小怪）
      for (const a of level.anchors) {
        if (!a.active) continue;
        const d = Silkhollow.dist(cx, cy, a.x, a.y);
        if (d <= range && d > 26 && level.hasLineOfSight(cx, cy, a.x, a.y)) {
          candidates.push({ type: 'anchor', ref: a, x: a.x, y: a.y, dist: d, priority: 1.18 });
        }
      }

      // 2) 共鸣丝铃
      for (const b of level.bells) {
        const d = Silkhollow.dist(cx, cy, b.x, b.y);
        if (d <= range && d > 26 && level.hasLineOfSight(cx, cy, b.x, b.y)) {
          candidates.push({ type: 'bell', ref: b, x: b.x, y: b.y, dist: d, priority: b.triggered ? 0.95 : 1.4 });
        }
      }

      // 3) 活体敌怪 / Boss
      for (const e of enemies) {
        if (e.dead || !e.active) continue;
        const ex = e.x + e.w * 0.5;
        const ey = e.y + e.h * 0.5;
        const d = Silkhollow.dist(cx, cy, ex, ey);
        if (d <= range && d > 36 && level.hasLineOfSight(cx, cy, ex, ey)) {
          const isStaggerBoss = e.isBoss && e.state === 'stagger';
          const basePrio = isStaggerBoss ? 2.4 : e.isBoss ? 1.15 : e.type === 'wisp' ? 1.1 : 0.95;
          candidates.push({
            type: 'enemy',
            ref: e,
            x: ex,
            y: ey,
            dist: d,
            priority: basePrio,
            isExec: isStaggerBoss,
          });
        }
      }

      if (candidates.length === 0) {
        this.bestTarget = null;
        return;
      }

      // 鼠标世界坐标与键盘方向混合打分
      const mouseWorldX = input.mouseX + camera.x;
      const mouseWorldY = input.mouseY + camera.y;
      const useMouse = input.mouseRecentlyMoved;

      let aimX = input.x !== 0 || input.y !== 0 ? input.x : this.facing;
      let aimY = input.x !== 0 || input.y !== 0 ? input.y : -0.38;
      if (useMouse) {
        aimX = mouseWorldX - cx;
        aimY = mouseWorldY - cy;
      }
      const aimLen = Math.hypot(aimX, aimY) || 1;
      aimX /= aimLen;
      aimY /= aimLen;

      let best = null;
      let bestScore = -Infinity;

      for (const c of candidates) {
        const dx = c.x - cx;
        const dy = c.y - cy;
        const len = c.dist || 1;
        const dot = (dx / len) * aimX + (dy / len) * aimY;

        let score = c.priority * 100 - c.dist * 0.16 + dot * 85;
        if (useMouse) {
          const cursorDist = Silkhollow.dist(mouseWorldX, mouseWorldY, c.x, c.y);
          if (cursorDist < 140) {
            score += (140 - cursorDist) * 1.15;
          }
        }
        // 如果完全在背后且不是 Boss 处决或紧邻鼠标，则降低权重
        if (dot < -0.35 && !c.isExec && (!useMouse || Silkhollow.dist(mouseWorldX, mouseWorldY, c.x, c.y) > 95)) {
          score -= 110;
        }
        if (score > bestScore) {
          bestScore = score;
          best = c;
        }
      }

      this.bestTarget = best;
    }

    startGrapple(target, input, world) {
      const g = this.grapple;
      g.state = 'shooting';
      g.tipX = this.cx;
      g.tipY = this.cy;
      g.anchorX = target.x;
      g.anchorY = target.y;
      g.target = target.ref;
      g.targetType = target.type;
      g.holdTime = 0;
      g.timer = 0;
      g.waveAmp = 14;
      g.releasedEarly = !input.grappleHeld;

      this.dashTimer = 0;
      this.isFocusing = false;
      this.focusProgress = 0;
      if (target.x !== this.cx) {
        this.facing = target.x > this.cx ? 1 : -1;
      }

      world.audio.playSilkShoot();
      world.particles.burst(this.cx, this.cy, 8, Silkhollow.COLORS.silkCyan, 160);
    }

    updateGrappleState(dt, input, world) {
      const g = this.grapple;
      const { level, particles, audio } = world;
      g.timer += dt;
      g.waveAmp = Math.max(0, g.waveAmp - dt * 52);

      // 若目标为动态敌人，实时追踪锚点坐标
      if (g.targetType === 'enemy' && g.target) {
        if (g.target.dead) {
          this.cancelGrapple(true);
          return;
        }
        g.anchorX = g.target.x + g.target.w * 0.5;
        g.anchorY = g.target.y + g.target.h * 0.5;
      }

      if (!input.grappleHeld) {
        g.releasedEarly = true;
      }

      // 阶段 A：渊丝高速射出
      if (g.state === 'shooting') {
        const dx = g.anchorX - g.tipX;
        const dy = g.anchorY - g.tipY;
        const d = Math.hypot(dx, dy);
        const step = CFG.GRAPPLE_SHOOT_SPEED * dt;

        // 射出期间人物轻微缓降，增强滞空质感
        this.vy = Math.min(this.vy + CFG.GRAVITY * 0.25 * dt, 180);
        this.moveAndCollide(dt, level);

        if (d <= step + 10 || g.timer > 0.22) {
          g.tipX = g.anchorX;
          g.tipY = g.anchorY;
          audio.playSilkLatch();
          particles.ring(g.anchorX, g.anchorY, Silkhollow.COLORS.silkBright, 26);

          if (g.targetType === 'bell') {
            g.state = 'bell_pull';
            g.timer = 0;
            level.triggerBell(g.target, world);
            this.vy = -445;
            this.vx = (g.anchorX - this.cx > 0 ? 1 : -1) * 180;
            this.resetAirResources();
          } else if (g.targetType === 'enemy') {
            g.state = 'enemy_zip';
            g.timer = 0;
            this.grappleInvuln = 0.26;
          } else {
            // 丝环锚点：依据是否已松手决定直接 Zip 还是进入短按/长按判定窗
            g.ropeLen = Silkhollow.clamp(Silkhollow.dist(this.cx, this.cy, g.anchorX, g.anchorY), CFG.SWING_MIN_LEN, this.grappleRange);
            if (g.releasedEarly) {
              g.state = 'zip';
              g.timer = 0;
            } else {
              g.state = 'latched';
              g.holdTime = 0;
            }
          }
        } else {
          g.tipX += (dx / d) * step;
          g.tipY += (dy / d) * step;
        }
        return;
      }

      // 阶段 B：拉响共鸣铃的短暂牵引特效
      if (g.state === 'bell_pull') {
        this.vy += CFG.GRAVITY * 0.85 * dt;
        this.moveAndCollide(dt, level);
        if (g.timer > 0.14) {
          this.cancelGrapple(true);
        }
        return;
      }

      // 阶段 C：锚点刚扣住（0 ~ 0.16s 区分短按弹射 vs 长按摆荡）
      if (g.state === 'latched') {
        g.holdTime += dt;
        const dx = g.anchorX - this.cx;
        const dy = g.anchorY - this.cy;
        const d = Math.hypot(dx, dy) || 1;
        // 轻微收紧预拉力，无论哪种模式都立刻获得正反馈
        this.vx = Silkhollow.lerp(this.vx, (dx / d) * 320, dt * 10);
        this.vy = Silkhollow.lerp(this.vy, (dy / d) * 320, dt * 10);
        this.moveAndCollide(dt, level);

        if (input.jumpPressed) {
          this.slingshotRelease(input, world);
          return;
        }
        if (!input.grappleHeld || g.releasedEarly) {
          g.state = 'zip';
          g.timer = 0;
          return;
        }
        if (g.holdTime >= CFG.GRAPPLE_HOLD_THRESHOLD) {
          g.state = 'swing';
          g.ropeLen = Silkhollow.clamp(Silkhollow.dist(this.cx, this.cy, g.anchorX, g.anchorY), CFG.SWING_MIN_LEN, Math.min(270, this.grappleRange));
          // 若当前几乎静止在锚点下方，赋予朝向方向的初始切向摆动
          if (Math.abs(this.vx) < 120) {
            this.vx += (input.x !== 0 ? input.x : this.facing) * 190;
          }
        }
        return;
      }

      // 阶段 D：短按高速弹射拉拽 (Zip-Pull)
      if (g.state === 'zip') {
        const dx = g.anchorX - this.cx;
        const dy = g.anchorY - this.cy;
        const d = Math.hypot(dx, dy) || 1;
        this.vx = (dx / d) * CFG.GRAPPLE_ZIP_SPEED;
        this.vy = (dy / d) * CFG.GRAPPLE_ZIP_SPEED;

        if (Math.random() < 0.65) {
          this.afterimages.push({ x: this.x, y: this.y, facing: this.facing, alpha: 0.45, tint: Silkhollow.COLORS.silkCyan });
        }

        const hitWall = this.moveAndCollide(dt, level);

        if (input.jumpPressed) {
          this.vx = (dx / d) * 360 + input.x * 120;
          this.vy = -560;
          audio.playJump(true);
          particles.burst(this.cx, this.cy, 12, Silkhollow.COLORS.silkBright, 220);
          this.cancelGrapple(true);
          return;
        }

        if (d < 34 || hitWall || g.timer > 0.48) {
          // 抵达锚点，优雅挑起并保留前冲动量
          this.vx = Silkhollow.clamp((dx / d) * 360 + input.x * 100, -480, 480);
          this.vy = Math.min((dy / d) * 320 - 175, -430);
          this.squashX = 0.8;
          this.squashY = 1.24;
          particles.burst(g.anchorX, g.anchorY, 10, Silkhollow.COLORS.silkCyan, 190);
          this.cancelGrapple(true);
        }
        return;
      }

      // 阶段 E：物理钟摆摆荡 (Pendulum Swing)
      if (g.state === 'swing') {
        g.tipX = g.anchorX;
        g.tipY = g.anchorY;

        // 上下微调绳长
        if (input.y !== 0) {
          g.ropeLen = Silkhollow.clamp(g.ropeLen + input.y * CFG.SWING_REEL_SPEED * dt, CFG.SWING_MIN_LEN, this.grappleRange);
        }

        // 重力
        this.vy += CFG.GRAVITY * 0.96 * dt;

        // 切向摆荡推力（左右键发力）
        let dx = this.cx - g.anchorX;
        let dy = this.cy - g.anchorY;
        let dist = Math.hypot(dx, dy) || 1;
        const tx = dy / dist;
        const ty = -dx / dist;

        if (input.x !== 0) {
          this.facing = input.x > 0 ? 1 : -1;
          this.vx += tx * input.x * CFG.SWING_PUMP_FORCE * dt;
          this.vy += ty * input.x * CFG.SWING_PUMP_FORCE * dt;
        }

        this.vx *= CFG.SWING_DAMPING;
        this.vy *= CFG.SWING_DAMPING;

        // 限速避免数值爆炸
        const spd = Math.hypot(this.vx, this.vy);
        if (spd > 820) {
          this.vx = (this.vx / spd) * 820;
          this.vy = (this.vy / spd) * 820;
        }

        this.moveAndCollide(dt, level);

        // 绳长硬约束投影
        dx = this.cx - g.anchorX;
        dy = this.cy - g.anchorY;
        dist = Math.hypot(dx, dy) || 1;
        if (dist > g.ropeLen) {
          const nx = dx / dist;
          const ny = dy / dist;
          const targetX = g.anchorX + nx * g.ropeLen - this.w * 0.5;
          const targetY = g.anchorY + ny * g.ropeLen - this.h * 0.5;
          if (!this.collidesSolidAt(targetX, targetY, level)) {
            this.x = targetX;
            this.y = targetY;
          } else {
            g.ropeLen = Math.min(dist, this.grappleRange);
          }
          // 消除径向向外速度，完整保留切向速度
          const radVel = this.vx * nx + this.vy * ny;
          if (radVel > 0) {
            this.vx -= radVel * nx;
            this.vy -= radVel * ny;
          }
        }

        // 摆荡中按跳：弹弓爆发抛射！
        if (input.jumpPressed) {
          this.slingshotRelease(input, world);
          return;
        }

        // 松开钩锁键：顺滑惯性释放
        if (!input.grappleHeld) {
          this.vx = Silkhollow.clamp(this.vx * 1.12, -590, 590);
          if (this.vy < 120) {
            this.vy = Math.min(this.vy * 1.05 - 90, -240);
          }
          particles.burst(this.cx, this.cy, 8, Silkhollow.COLORS.silkCyan, 150);
          this.cancelGrapple(true);
        }
        return;
      }

      // 阶段 F：钩敌突进 / Boss 丝核处决 (Harpoon Zip)
      if (g.state === 'enemy_zip') {
        const enemy = g.target;
        const dx = g.anchorX - this.cx;
        const dy = g.anchorY - this.cy;
        const d = Math.hypot(dx, dy) || 1;
        const speed = CFG.GRAPPLE_ZIP_SPEED * 1.12;
        this.vx = (dx / d) * speed;
        this.vy = (dy / d) * speed;

        if (Math.random() < 0.75) {
          this.afterimages.push({ x: this.x, y: this.y, facing: this.facing, alpha: 0.55, tint: Silkhollow.COLORS.silkBright });
        }

        const hitWall = this.moveAndCollide(dt, level);

        if (d < Math.max(44, (enemy.w + this.w) * 0.55) || hitWall || g.timer > 0.44) {
          this.grappleInvuln = 0.25;
          if (enemy && !enemy.dead) {
            if (enemy.isBoss && enemy.state === 'stagger') {
              // 渊丝失衡处决！！
              enemy.takeDamage(58, this.facing, world, true, true);
              this.gainSoul(28);
              world.triggerHitstop(CFG.HITSTOP_EXEC);
              world.camera.shake(14, 0.34);
              audio.playSilkExecution();
              particles.burst(g.anchorX, g.anchorY, 36, Silkhollow.COLORS.silkCyan, 420);
              particles.burst(g.anchorX, g.anchorY, 20, Silkhollow.COLORS.corruptGold, 300);
              particles.ring(g.anchorX, g.anchorY, Silkhollow.COLORS.silkBright, 95);
              this.vx = -this.facing * 280;
              this.vy = -460;
            } else {
              // 常规钩敌突进：附带微伤 + 弹起（方便接下劈或钩刃强化斩）
              enemy.takeDamage(8, this.facing, world, false, false);
              this.gainSoul(6);
              this.hookEmpowerTimer = CFG.HOOK_EMPOWER_TIME;
              world.triggerHitstop(0.035);
              world.camera.shake(5, 0.14);
              audio.playNailHit(false);
              particles.burst(g.anchorX, g.anchorY, 14, Silkhollow.COLORS.silkCyan, 240);
              this.vx = -Math.sign(dx || this.facing) * 140;
              this.vy = -395;
            }
          }
          this.cancelGrapple(true);
        }
      }
    }

    slingshotRelease(input, world) {
      this.vx = Silkhollow.clamp(this.vx * CFG.SWING_SLINGSHOT_BOOST + input.x * 165, -650, 650);
      this.vy = Math.min(this.vy * 0.65 - 240, CFG.SWING_SLINGSHOT_VY);
      this.squashX = 0.76;
      this.squashY = 1.28;
      world.audio.playSlingshot();
      world.particles.burst(this.cx, this.cy, 16, Silkhollow.COLORS.silkBright, 260);
      world.camera.shake(3.5, 0.1);
      this.cancelGrapple(true);
    }

    updateDash(dt, world) {
      this.dashTimer -= dt;
      this.vx = this.dashDir * CFG.DASH_SPEED;
      this.vy = 0;

      if (Math.random() < 0.85) {
        this.afterimages.push({ x: this.x, y: this.y, facing: this.facing, alpha: 0.58, tint: Silkhollow.COLORS.paleBlue });
      }
      this.moveAndCollide(dt, world.level);

      if (this.dashTimer <= 0) {
        this.vx *= 0.45;
      }
    }

    updateStandardMovement(dt, input, world) {
      const { level, particles, audio } = world;

      // 凝聚回血时锁住位移，直到松开或受击
      if (this.isFocusing) {
        this.vx *= 0.7;
        this.vy += CFG.GRAVITY * dt;
        this.moveAndCollide(dt, level);
        return;
      }

      // 幽影冲刺触发
      if (input.dashPressed && this.canDash && this.dashCooldown <= 0) {
        this.dashTimer = CFG.DASH_DURATION;
        this.dashCooldown = CFG.DASH_COOLDOWN;
        this.canDash = this.onGround; // 地面冲刺落地刷新，空中限一次
        this.dashDir = input.x !== 0 ? Math.sign(input.x) : (this.wallSlide ? -this.wallDir : this.facing);
        this.facing = this.dashDir;
        this.squashX = 1.3;
        this.squashY = 0.76;
        audio.playDash();
        particles.burst(this.cx, this.cy, 12, Silkhollow.COLORS.paleBlue, 200);
        return;
      }

      // 水平移动（零拖泥带水的精准加减速）
      if (this.wallJumpLockTimer <= 0) {
        const accel = this.onGround ? CFG.GROUND_ACCEL : CFG.AIR_ACCEL;
        const decel = this.onGround ? CFG.GROUND_DECEL : CFG.AIR_DECEL;
        if (input.x !== 0) {
          this.facing = input.x > 0 ? 1 : -1;
          const targetVx = input.x * CFG.MOVE_SPEED;
          if (Math.abs(this.vx) > CFG.MOVE_SPEED && Math.sign(this.vx) === Math.sign(input.x)) {
            // 保留来自摆荡弹射的超高动量并温和衰减
            this.vx = Silkhollow.lerp(this.vx, targetVx, dt * 2.4);
          } else {
            this.vx = moveTowards(this.vx, targetVx, accel * dt);
          }
        } else {
          this.vx = moveTowards(this.vx, 0, decel * dt);
        }
      }

      // 检测贴墙滑行
      this.wallSlide = !this.onGround && this.wallDir !== 0 && this.vy > 0 && input.x === this.wallDir;

      // 重力与最大下落速度
      this.vy += CFG.GRAVITY * dt;
      const maxFall = this.wallSlide ? CFG.WALL_SLIDE_SPEED : CFG.MAX_FALL_SPEED;
      if (this.vy > maxFall) this.vy = maxFall;

      if (this.wallSlide && Math.random() < 0.28) {
        particles.spawn(
          this.wallDir > 0 ? this.x + this.w : this.x,
          this.y + 10 + Math.random() * 24,
          -this.wallDir * 25,
          -20 - Math.random() * 20,
          2.2,
          0.35,
          '#94a3b8'
        );
      }

      // 跳跃判定（含穿透单向平台、土狼时间、蹬墙跳与丝翼二段跳）
      if (this.jumpBufferTimer > 0) {
        // 下 + 跳：穿过单向平台
        if (this.onGround && input.y > 0 && this.isStandingOnPlatform(level)) {
          this.dropThroughTimer = 0.22;
          this.y += 4;
          this.onGround = false;
          this.jumpBufferTimer = 0;
        } else if (this.coyoteTimer > 0) {
          // 常规地面起跳
          this.vy = CFG.JUMP_VEL;
          this.onGround = false;
          this.coyoteTimer = 0;
          this.jumpBufferTimer = 0;
          this.squashX = 0.78;
          this.squashY = 1.24;
          audio.playJump(false);
          particles.burst(this.cx, this.y + this.h, 7, '#cbd5e1', 110);
        } else if (this.wallDir !== 0 && !this.onGround) {
          // 蹬墙跳
          this.vx = -this.wallDir * CFG.WALL_JUMP_VX;
          this.vy = CFG.WALL_JUMP_VY;
          this.facing = -this.wallDir;
          this.wallJumpLockTimer = CFG.WALL_JUMP_LOCK;
          this.jumpBufferTimer = 0;
          this.squashX = 0.76;
          this.squashY = 1.24;
          audio.playJump(false);
          particles.burst(this.wallDir > 0 ? this.x + this.w : this.x, this.cy, 9, '#cbd5e1', 150);
        } else if (this.canDoubleJump) {
          // 苍白丝翼二段跳
          this.vy = CFG.DOUBLE_JUMP_VEL;
          this.canDoubleJump = false;
          this.jumpBufferTimer = 0;
          this.squashX = 0.8;
          this.squashY = 1.22;
          audio.playJump(true);
          particles.burst(this.cx, this.y + this.h, 14, Silkhollow.COLORS.silkBright, 190);
        }
      }

      // 可变跳高度：提前松手削减上升速度
      if (!input.jumpHeld && this.vy < -150) {
        this.vy *= Math.pow(CFG.JUMP_CUT_MULT, dt * 22);
      }

      const wasOnGround = this.onGround;
      this.moveAndCollide(dt, level);

      if (this.onGround) {
        this.coyoteTimer = CFG.COYOTE_TIME;
        this.canDash = true;
        this.canDoubleJump = this.hasSilkWings;
        if (!wasOnGround) {
          this.squashX = 1.24;
          this.squashY = 0.78;
          audio.playLand();
          particles.burst(this.cx, this.y + this.h, 6, '#94a3b8', 90);
        }
        // 记录安全立足点（非边缘尖刺旁）
        if (!this.isNearHazard(level)) {
          this.lastSafeX = this.x;
          this.lastSafeY = this.y;
        }
      }
    }

    updateSoulSystem(dt, input, world) {
      const { particles, audio } = world;
      if (input.soulHeld && this.soul >= CFG.SOUL_COST && this.grapple.state === 'idle' && this.dashTimer <= 0) {
        this.soulHoldTime += dt;
        // 地面长按 > 0.18s 且未满血 -> 凝聚回血
        if (this.onGround && this.hp < this.maxHp && this.soulHoldTime > 0.18) {
          if (!this.isFocusing) {
            this.isFocusing = true;
            audio.playFocusHum();
          }
          this.focusProgress += dt / CFG.FOCUS_DURATION;
          // 汇聚粒子
          if (Math.random() < 0.6) {
            const ang = Math.random() * Math.PI * 2;
            const rad = 36 + Math.random() * 20;
            particles.spawn(
              this.cx + Math.cos(ang) * rad,
              this.cy + Math.sin(ang) * rad,
              -Math.cos(ang) * 95,
              -Math.sin(ang) * 95,
              2.6,
              0.38,
              Silkhollow.COLORS.paleWhite
            );
          }
          if (this.focusProgress >= 1) {
            this.soul -= CFG.SOUL_COST;
            this.hp = Math.min(this.maxHp, this.hp + 1);
            this.focusProgress = 0;
            this.soulHoldTime = 0;
            this.isFocusing = false;
            this.healBurstTimer = 0.55;
            audio.playHealComplete();
            particles.burst(this.cx, this.cy, 24, Silkhollow.COLORS.paleWhite, 240);
            particles.ring(this.cx, this.cy, Silkhollow.COLORS.paleBlue, 62);
            world.camera.shake(4, 0.15);
          }
        }
      } else {
        // 短按释放：发射灵魂脉冲弹！
        if (this.soulHoldTime > 0 && this.soulHoldTime < 0.24 && !this.isFocusing && this.soul >= CFG.SOUL_COST && this.soulCastCooldown <= 0) {
          this.castSoulBolt(world);
        }
        this.soulHoldTime = 0;
        this.isFocusing = false;
        this.focusProgress = 0;
      }
    }

    castSoulBolt(world) {
      this.soul -= CFG.SOUL_COST;
      this.soulCastCooldown = 0.32;
      const dir = this.facing;
      this.soulBolts.push({
        x: this.cx + dir * 20,
        y: this.cy - 2,
        vx: dir * CFG.SOUL_BOLT_SPEED,
        radius: 15,
        life: 0.9,
        dir,
        hitIds: new Set(),
      });
      this.vx -= dir * 180; // 空洞骑士风轻微后坐力
      world.audio.playSoulCast();
      world.camera.shake(5, 0.14);
      world.particles.burst(this.cx + dir * 18, this.cy, 14, Silkhollow.COLORS.paleBlue, 220);
    }

    updateSoulBolts(dt, world) {
      const { level, enemies, particles } = world;
      for (let i = this.soulBolts.length - 1; i >= 0; i--) {
        const b = this.soulBolts[i];
        b.x += b.vx * dt;
        b.life -= dt;

        if (Math.random() < 0.7) {
          particles.spawn(b.x, b.y + (Math.random() - 0.5) * 14, -b.vx * 0.1, (Math.random() - 0.5) * 30, 3.2, 0.28, Silkhollow.COLORS.paleBlue);
        }

        // 命中敌人（可穿透）
        for (const e of enemies) {
          if (e.dead || !e.active || b.hitIds.has(e.id)) continue;
          if (b.x + b.radius > e.x && b.x - b.radius < e.x + e.w && b.y + b.radius > e.y && b.y - b.radius < e.y + e.h) {
            b.hitIds.add(e.id);
            e.takeDamage(CFG.SOUL_BOLT_DAMAGE, b.dir, world, true, false);
            world.triggerHitstop(0.04);
            world.camera.shake(6, 0.15);
            particles.burst(b.x, b.y, 16, Silkhollow.COLORS.paleWhite, 260);
          }
        }

        // 撞墙消散
        const tx = Math.floor(b.x / TS);
        const ty = Math.floor(b.y / TS);
        if (b.life <= 0 || level.isSolidTile(tx, ty)) {
          particles.burst(b.x, b.y, 10, Silkhollow.COLORS.paleBlue, 160);
          this.soulBolts.splice(i, 1);
        }
      }
    }

    startSlash(input, world) {
      let dir = this.facing > 0 ? 'right' : 'left';
      if (input.y < 0) dir = 'up';
      else if (input.y > 0 && !this.onGround) dir = 'down';

      const empowered = this.hookEmpowerTimer > 0;
      this.nailCooldown = CFG.NAIL_COOLDOWN;
      this.slash = {
        dir,
        timer: CFG.NAIL_DURATION,
        duration: CFG.NAIL_DURATION,
        empowered,
        hitIds: new Set(),
        pogoTriggered: false,
      };
      world.audio.playNailSwing(empowered);
    }

    getSlashBox() {
      if (!this.slash) return null;
      const range = this.slash.empowered ? CFG.NAIL_RANGE * 1.18 : CFG.NAIL_RANGE;
      const width = this.slash.empowered ? CFG.NAIL_WIDTH * 1.15 : CFG.NAIL_WIDTH;
      const cx = this.cx;
      const cy = this.cy;

      switch (this.slash.dir) {
        case 'right': return { x: cx + 4, y: cy - width * 0.52, w: range, h: width };
        case 'left': return { x: cx - 4 - range, y: cy - width * 0.52, w: range, h: width };
        case 'up': return { x: cx - width * 0.58, y: cy - 8 - range, w: width * 1.16, h: range };
        case 'down': return { x: cx - width * 0.62, y: cy + 4, w: width * 1.24, h: range };
      }
      return null;
    }

    updateSlash(dt, world) {
      const s = this.slash;
      s.timer -= dt;
      const box = this.getSlashBox();

      if (box && s.timer > 0) {
        const { enemies, level, particles, audio } = world;
        const dmg = Math.round(CFG.NAIL_DAMAGE * (s.empowered ? CFG.HOOK_EMPOWER_MULT : 1));

        // 1) 命中敌人
        for (const e of enemies) {
          if (e.dead || !e.active || s.hitIds.has(e.id)) continue;
          if (Silkhollow.aabb(box, e)) {
            s.hitIds.add(e.id);
            const hitDir = s.dir === 'left' ? -1 : s.dir === 'right' ? 1 : this.facing;
            const blocked = e.isShieldBlocked && e.isShieldBlocked(this, s.dir);

            if (blocked) {
              // 腐甲卫士正面格挡
              audio.playClang();
              particles.burst(e.x + e.w * 0.5, e.y + e.h * 0.4, 10, '#fde68a', 220);
              this.vx = -hitDir * 240;
              world.camera.shake(4, 0.1);
            } else {
              e.takeDamage(dmg, hitDir, world, s.empowered, false);
              this.gainSoul(s.empowered ? CFG.SOUL_GAIN_HOOK_HIT : CFG.SOUL_GAIN_HIT);
              if (s.empowered) this.hookEmpowerTimer = 0;

              world.triggerHitstop(s.empowered ? CFG.HITSTOP_CRIT : CFG.HITSTOP_NAIL);
              world.camera.shake(s.empowered ? 8 : 4.5, s.empowered ? 0.18 : 0.11);
              audio.playNailHit(s.empowered);
              particles.burst(
                e.x + e.w * 0.5,
                e.y + e.h * 0.5,
                s.empowered ? 18 : 11,
                s.empowered ? Silkhollow.COLORS.silkCyan : Silkhollow.COLORS.corruptOrange,
                250
              );

              if (s.dir === 'down' && !s.pogoTriggered) {
                this.triggerPogo(world, false);
                s.pogoTriggered = true;
              } else if (s.dir === 'left' || s.dir === 'right') {
                this.vx = -hitDir * 145; // 空洞骑士标志性微击退
              }
            }
          }
        }

        // 2) 下劈弹反尖刺（Pogo on Spikes！）
        if (s.dir === 'down' && !s.pogoTriggered) {
          if (level.boxTouchesSpikes(box)) {
            s.pogoTriggered = true;
            this.triggerPogo(world, true);
            particles.burst(this.cx, box.y + box.h * 0.75, 12, '#e2e8f0', 220);
          }
        }

        // 3) 骨钉敲响共鸣铃
        for (const b of level.bells) {
          if (s.hitIds.has(b.id)) continue;
          const bRect = { x: b.x - 18, y: b.y - 18, w: 36, h: 36 };
          if (Silkhollow.aabb(box, bRect)) {
            s.hitIds.add(b.id);
            level.triggerBell(b, world);
            if (s.dir === 'down' && !s.pogoTriggered) {
              s.pogoTriggered = true;
              this.triggerPogo(world, true);
            }
          }
        }
      }

      if (s.timer <= 0) {
        this.slash = null;
      }
    }

    triggerPogo(world, metallic) {
      this.vy = CFG.POGO_VEL;
      this.resetAirResources();
      this.squashX = 0.82;
      this.squashY = 1.2;
      if (metallic) {
        world.audio.playClang();
        world.triggerHitstop(0.032);
        world.camera.shake(3.5, 0.09);
      }
    }

    gainSoul(amount) {
      this.soul = Math.min(CFG.SOUL_MAX, this.soul + amount);
    }

    takeDamage(amount, sourceX, world, isSpike) {
      if (this.invulnTimer > 0 || (this.grappleInvuln > 0 && !isSpike)) return false;

      this.hp = Math.max(0, this.hp - amount);
      this.invulnTimer = CFG.INVULN_TIME;
      this.hurtFlash = 0.35;
      this.isFocusing = false;
      this.focusProgress = 0;
      this.dashTimer = 0;
      this.cancelGrapple(false);

      const knockDir = sourceX !== undefined ? (this.cx >= sourceX ? 1 : -1) : -this.facing;
      this.vx = knockDir * 290;
      this.vy = -340;

      world.stats.damageTaken += amount;
      world.triggerHitstop(CFG.HITSTOP_HURT);
      world.camera.shake(11, 0.28);
      world.audio.playPlayerHurt();
      world.particles.burst(this.cx, this.cy, 22, Silkhollow.COLORS.paleWhite, 280);
      world.particles.burst(this.cx, this.cy, 12, Silkhollow.COLORS.corruptRed, 220);

      if (this.hp <= 0) {
        world.onPlayerDeath();
      } else if (isSpike) {
        // 尖刺传送回最近安全立足点
        this.x = this.lastSafeX;
        this.y = this.lastSafeY - 6;
        this.vx = 0;
        this.vy = -120;
        this.resetCloak();
        world.particles.ring(this.cx, this.cy, Silkhollow.COLORS.paleBlue, 45);
      }
      return true;
    }

    checkHazardSpikes(world) {
      const hurtBox = { x: this.x + 4, y: this.y + 5, w: this.w - 8, h: this.h - 9 };
      if (world.level.boxTouchesSpikes(hurtBox)) {
        this.takeDamage(1, this.cx, world, true);
      }
    }

    isStandingOnPlatform(level) {
      const tx1 = Math.floor((this.x + 2) / TS);
      const tx2 = Math.floor((this.x + this.w - 2) / TS);
      const ty = Math.floor((this.y + this.h + 2) / TS);
      for (let tx = tx1; tx <= tx2; tx++) {
        if (level.getTile(tx, ty) === TILE.PLATFORM) return true;
      }
      return false;
    }

    isNearHazard(level) {
      const box = { x: this.x - 6, y: this.y - 4, w: this.w + 12, h: this.h + 12 };
      return level.boxTouchesSpikes(box);
    }

    collidesSolidAt(x, y, level) {
      const rect = { x, y, w: this.w, h: this.h };
      const minTx = Math.floor(rect.x / TS);
      const maxTx = Math.floor((rect.x + rect.w - 0.01) / TS);
      const minTy = Math.floor(rect.y / TS);
      const maxTy = Math.floor((rect.y + rect.h - 0.01) / TS);
      for (let ty = minTy; ty <= maxTy; ty++) {
        for (let tx = minTx; tx <= maxTx; tx++) {
          if (level.isSolidTile(tx, ty)) return true;
        }
      }
      for (const g of level.getClosedGateRects()) {
        if (Silkhollow.aabb(rect, g)) return true;
      }
      return false;
    }

    moveAndCollide(dt, level) {
      let hitWall = false;
      const gates = level.getClosedGateRects();

      // 1) 水平轴移动与碰撞
      this.x += this.vx * dt;
      this.wallDir = 0;

      let minTx = Math.floor(this.x / TS);
      let maxTx = Math.floor((this.x + this.w - 0.01) / TS);
      let minTy = Math.floor((this.y + 2) / TS);
      let maxTy = Math.floor((this.y + this.h - 2) / TS);

      for (let ty = minTy; ty <= maxTy; ty++) {
        for (let tx = minTx; tx <= maxTx; tx++) {
          if (level.isSolidTile(tx, ty)) {
            if (this.vx > 0) {
              this.x = tx * TS - this.w;
              this.vx = 0;
              this.wallDir = 1;
              hitWall = true;
            } else if (this.vx < 0) {
              this.x = (tx + 1) * TS;
              this.vx = 0;
              this.wallDir = -1;
              hitWall = true;
            }
          }
        }
      }
      for (const g of gates) {
        if (Silkhollow.aabb(this, g)) {
          if (this.vx > 0) {
            this.x = g.x - this.w;
            this.vx = 0;
            this.wallDir = 1;
            hitWall = true;
          } else if (this.vx < 0) {
            this.x = g.x + g.w;
            this.vx = 0;
            this.wallDir = -1;
            hitWall = true;
          }
        }
      }

      // 贴墙检测（即使速度为 0 也保持贴墙状态便于蹬墙跳）
      if (this.wallDir === 0) {
        if (this.collidesSolidAt(this.x + 2, this.y + 4, level)) this.wallDir = 1;
        else if (this.collidesSolidAt(this.x - 2, this.y + 4, level)) this.wallDir = -1;
      }

      // 2) 垂直轴移动与碰撞
      const prevBottom = this.y + this.h;
      this.y += this.vy * dt;
      this.onGround = false;

      minTx = Math.floor((this.x + 1) / TS);
      maxTx = Math.floor((this.x + this.w - 1.01) / TS);
      minTy = Math.floor(this.y / TS);
      maxTy = Math.floor((this.y + this.h - 0.01) / TS);

      for (let ty = minTy; ty <= maxTy; ty++) {
        for (let tx = minTx; tx <= maxTx; tx++) {
          const t = level.getTile(tx, ty);
          if (level.isSolidTile(tx, ty)) {
            if (this.vy > 0) {
              this.y = ty * TS - this.h;
              this.vy = 0;
              this.onGround = true;
            } else if (this.vy < 0) {
              this.y = (ty + 1) * TS;
              this.vy = 0;
            }
          } else if (t === TILE.PLATFORM && this.vy >= 0 && this.dropThroughTimer <= 0) {
            const platTop = ty * TS;
            if (prevBottom <= platTop + 8) {
              this.y = platTop - this.h;
              this.vy = 0;
              this.onGround = true;
            }
          }
        }
      }
      for (const g of gates) {
        if (Silkhollow.aabb(this, g)) {
          if (this.vy > 0) {
            this.y = g.y - this.h;
            this.vy = 0;
            this.onGround = true;
          } else if (this.vy < 0) {
            this.y = g.y + g.h;
            this.vy = 0;
          }
        }
      }

      return hitWall;
    }

    updateCloak(dt) {
      const anchorX = this.cx - this.facing * 2;
      const anchorY = this.y + 15;
      const windX = -this.facing * 26 - this.vx * 0.16;

      this.cloak[0].x = anchorX;
      this.cloak[0].y = anchorY;

      for (let i = 1; i < this.cloak.length; i++) {
        const p = this.cloak[i];
        const vx = (p.x - p.ox) * 0.84;
        const vy = (p.y - p.oy) * 0.84;
        p.ox = p.x;
        p.oy = p.y;
        p.x += vx + (windX + Math.sin(this.animTime * 6 + i) * 14) * dt;
        p.y += vy + 210 * dt;
      }

      const segLen = 5.4;
      for (let iter = 0; iter < 4; iter++) {
        this.cloak[0].x = anchorX;
        this.cloak[0].y = anchorY;
        for (let i = 1; i < this.cloak.length; i++) {
          const prev = this.cloak[i - 1];
          const curr = this.cloak[i];
          const dx = curr.x - prev.x;
          const dy = curr.y - prev.y;
          const d = Math.hypot(dx, dy) || 0.001;
          const diff = (d - segLen) / d;
          curr.x -= dx * diff;
          curr.y -= dy * diff;
        }
      }
    }
  }

  function moveTowards(current, target, maxDelta) {
    if (Math.abs(target - current) <= maxDelta) return target;
    return current + Math.sign(target - current) * maxDelta;
  }

  Silkhollow.Player = Player;
})(window);
