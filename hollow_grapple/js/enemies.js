(function (global) {
  'use strict';

  const Silkhollow = (global.Silkhollow = global.Silkhollow || {});
  const CFG = Silkhollow.CFG;
  const TS = Silkhollow.TILE_SIZE;

  let nextEnemyId = 1;

  class EnemyBase {
    constructor(type, x, y, w, h, hp, shardReward) {
      this.id = 'e_' + nextEnemyId++;
      this.type = type;
      this.isBoss = false;
      this.x = x;
      this.y = y;
      this.w = w;
      this.h = h;
      this.vx = 0;
      this.vy = 0;
      this.facing = -1;
      this.maxHp = hp;
      this.hp = hp;
      this.shardReward = shardReward;
      this.dead = false;
      this.active = true;
      this.hurtTimer = 0;
      this.animTime = Math.random() * 10;
    }

    get cx() { return this.x + this.w * 0.5; }
    get cy() { return this.y + this.h * 0.5; }

    takeDamage(dmg, hitDir, world, isCrit) {
      if (this.dead) return;
      this.hp -= dmg;
      this.hurtTimer = 0.16;
      if (!this.isBoss) {
        this.vx = (hitDir || 1) * (isCrit ? 220 : 145);
        this.vy = -120;
      }
      if (this.hp <= 0) {
        this.die(world);
      }
    }

    die(world) {
      this.dead = true;
      world.stats.enemiesDefeated += 1;
      world.player.shards += this.shardReward;
      world.audio.playEnemyDeath();
      world.particles.burst(this.cx, this.cy, 22, Silkhollow.COLORS.corruptOrange, 260);
      world.particles.burst(this.cx, this.cy, 10, Silkhollow.COLORS.paleWhite, 180);
    }

    moveSolid(dt, level) {
      this.x += this.vx * dt;
      let hitWall = false;
      let minTx = Math.floor(this.x / TS);
      let maxTx = Math.floor((this.x + this.w - 0.01) / TS);
      let minTy = Math.floor((this.y + 2) / TS);
      let maxTy = Math.floor((this.y + this.h - 2) / TS);
      for (let ty = minTy; ty <= maxTy; ty++) {
        for (let tx = minTx; tx <= maxTx; tx++) {
          if (level.isSolidTile(tx, ty)) {
            if (this.vx > 0) this.x = tx * TS - this.w;
            else if (this.vx < 0) this.x = (tx + 1) * TS;
            this.vx = 0;
            hitWall = true;
          }
        }
      }

      this.y += this.vy * dt;
      this.onGround = false;
      minTx = Math.floor((this.x + 2) / TS);
      maxTx = Math.floor((this.x + this.w - 2.01) / TS);
      minTy = Math.floor(this.y / TS);
      maxTy = Math.floor((this.y + this.h - 0.01) / TS);
      for (let ty = minTy; ty <= maxTy; ty++) {
        for (let tx = minTx; tx <= maxTx; tx++) {
          if (level.isSolidTile(tx, ty) || (level.getTile(tx, ty) === Silkhollow.TILE.PLATFORM && this.vy >= 0)) {
            if (this.vy > 0) {
              this.y = ty * TS - this.h;
              this.vy = 0;
              this.onGround = true;
            } else if (this.vy < 0 && level.isSolidTile(tx, ty)) {
              this.y = (ty + 1) * TS;
              this.vy = 0;
            }
          }
        }
      }
      return hitWall;
    }

    checkPlayerContact(player, world) {
      if (this.dead || !this.active) return;
      const box = { x: this.x + 3, y: this.y + 3, w: this.w - 6, h: this.h - 6 };
      if (Silkhollow.aabb(box, player)) {
        player.takeDamage(1, this.cx, world, false);
      }
    }
  }

  // 1) 腐壳爬虫 (Crawler)
  class Crawler extends EnemyBase {
    constructor(spawn) {
      super('crawler', spawn.x, spawn.y, 34, 24, 34, 10);
      this.minX = spawn.minX;
      this.maxX = spawn.maxX;
      this.speed = 68;
      this.facing = 1;
    }

    update(dt, world) {
      if (this.dead) return;
      this.animTime += dt;
      if (this.hurtTimer > 0) this.hurtTimer -= dt;
      if (this.hurtTimer <= 0) {
        this.vx = this.facing * this.speed;
      }
      this.vy += CFG.GRAVITY * dt;
      const hitWall = this.moveSolid(dt, world.level);

      // 边界与悬崖折返
      const aheadTx = Math.floor((this.facing > 0 ? this.x + this.w + 4 : this.x - 4) / TS);
      const footTy = Math.floor((this.y + this.h + 4) / TS);
      const noFloor = !world.level.isSolidTile(aheadTx, footTy) && world.level.getTile(aheadTx, footTy) !== Silkhollow.TILE.PLATFORM;

      if (hitWall || noFloor || this.x < this.minX || this.x + this.w > this.maxX) {
        this.facing *= -1;
      }
      this.checkPlayerContact(world.player, world);
    }
  }

  // 2) 孢子幽灵 (Spore Wisp - 浮空可钩锁跳板 + 远程追踪孢子)
  class SporeWisp extends EnemyBase {
    constructor(spawn) {
      super('wisp', spawn.x, spawn.y, 32, 32, 36, 15);
      this.homeX = spawn.x;
      this.homeY = spawn.y;
      this.shootTimer = 1.6 + Math.random() * 1.2;
    }

    update(dt, world) {
      if (this.dead) return;
      this.animTime += dt;
      if (this.hurtTimer > 0) this.hurtTimer -= dt;

      const targetX = this.homeX + Math.sin(this.animTime * 1.6) * 28;
      const targetY = this.homeY + Math.cos(this.animTime * 2.3) * 18;
      if (this.hurtTimer <= 0) {
        this.vx = Silkhollow.lerp(this.vx, (targetX - this.x) * 3.5, dt * 5);
        this.vy = Silkhollow.lerp(this.vy, (targetY - this.y) * 3.5, dt * 5);
      } else {
        this.vx *= 0.92;
        this.vy *= 0.92;
      }
      this.x += this.vx * dt;
      this.y += this.vy * dt;

      const d = Silkhollow.dist(this.cx, this.cy, world.player.cx, world.player.cy);
      this.facing = world.player.cx > this.cx ? 1 : -1;

      if (d < 460) {
        this.shootTimer -= dt;
        if (this.shootTimer <= 0) {
          this.shootTimer = 2.6;
          const dx = world.player.cx - this.cx;
          const dy = world.player.cy - this.cy;
          const len = Math.hypot(dx, dy) || 1;
          world.enemyProjectiles.push({
            x: this.cx,
            y: this.cy,
            vx: (dx / len) * 235,
            vy: (dy / len) * 235,
            radius: 7,
            life: 2.6,
            color: Silkhollow.COLORS.corruptOrange,
          });
          world.particles.burst(this.cx, this.cy, 6, Silkhollow.COLORS.corruptOrange, 120);
        }
      }
      this.checkPlayerContact(world.player, world);
    }
  }

  // 3) 苔跃虫 (Moss Hopper)
  class MossHopper extends EnemyBase {
    constructor(spawn) {
      super('hopper', spawn.x, spawn.y, 34, 30, 52, 18);
      this.minX = spawn.minX;
      this.maxX = spawn.maxX;
      this.hopCooldown = 1.0;
      this.telegraph = 0;
    }

    update(dt, world) {
      if (this.dead) return;
      this.animTime += dt;
      if (this.hurtTimer > 0) this.hurtTimer -= dt;
      this.vy += CFG.GRAVITY * dt;

      const d = Silkhollow.dist(this.cx, this.cy, world.player.cx, world.player.cy);
      if (this.onGround && this.hurtTimer <= 0) {
        this.vx *= 0.78;
        this.hopCooldown -= dt;
        if (this.telegraph > 0) {
          this.telegraph -= dt;
          if (this.telegraph <= 0) {
            this.facing = world.player.cx >= this.cx ? 1 : -1;
            this.vx = this.facing * 265;
            this.vy = -485;
            this.hopCooldown = 1.35;
          }
        } else if (this.hopCooldown <= 0 && d < 420) {
          this.telegraph = 0.28;
        }
      }

      this.moveSolid(dt, world.level);
      this.x = Silkhollow.clamp(this.x, this.minX, this.maxX);
      this.checkPlayerContact(world.player, world);
    }
  }

  // 4) 腐甲卫士 (Husk Knight - 正面格挡，鼓励钩锁越顶绕背或下劈头顶！)
  class HuskKnight extends EnemyBase {
    constructor(spawn) {
      super('knight', spawn.x, spawn.y, 40, 56, 95, 35);
      this.minX = spawn.minX;
      this.maxX = spawn.maxX;
      this.state = 'patrol'; // patrol | windup | lunge | recover
      this.stateTimer = 0;
    }

    isShieldBlocked(player, slashDir) {
      if (this.state === 'windup' || this.state === 'lunge' || this.state === 'recover') return false;
      if (slashDir === 'down' || slashDir === 'up') return false;
      // 玩家在卫士正面水平劈砍则被重盾挡下
      const playerInFront = (this.facing > 0 && player.cx > this.cx) || (this.facing < 0 && player.cx < this.cx);
      return playerInFront;
    }

    update(dt, world) {
      if (this.dead) return;
      this.animTime += dt;
      if (this.hurtTimer > 0) this.hurtTimer -= dt;
      this.vy += CFG.GRAVITY * dt;

      const dx = world.player.cx - this.cx;
      const dy = Math.abs(world.player.cy - this.cy);
      const dist = Math.abs(dx);

      if (this.state === 'patrol') {
        if (dist < 260 && dy < 90) {
          this.facing = dx >= 0 ? 1 : -1;
          if (dist < 135) {
            this.state = 'windup';
            this.stateTimer = 0.48;
            this.vx = 0;
          } else {
            this.vx = this.facing * 92;
          }
        } else {
          this.vx = this.facing * 52;
          if (this.x <= this.minX + 6) this.facing = 1;
          if (this.x + this.w >= this.maxX - 6) this.facing = -1;
        }
      } else if (this.state === 'windup') {
        this.vx *= 0.8;
        this.stateTimer -= dt;
        if (this.stateTimer <= 0) {
          this.state = 'lunge';
          this.stateTimer = 0.28;
          this.vx = this.facing * 390;
          world.audio.playNailSwing(false);
        }
      } else if (this.state === 'lunge') {
        this.stateTimer -= dt;
        // 斩击波前伸判定
        const bladeBox = {
          x: this.facing > 0 ? this.x + this.w - 4 : this.x - 34,
          y: this.y + 8,
          w: 38,
          h: 36,
        };
        if (Silkhollow.aabb(bladeBox, world.player)) {
          world.player.takeDamage(1, this.cx, world, false);
        }
        if (this.stateTimer <= 0) {
          this.state = 'recover';
          this.stateTimer = 0.72;
          this.vx = 0;
        }
      } else if (this.state === 'recover') {
        this.vx *= 0.85;
        this.stateTimer -= dt;
        if (this.stateTimer <= 0) {
          this.state = 'patrol';
        }
      }

      this.moveSolid(dt, world.level);
      this.x = Silkhollow.clamp(this.x, this.minX, this.maxX);
      this.checkPlayerContact(world.player, world);
    }
  }

  // 5) 多阶段 Boss：残丝监守者 · 维洛斯 (Velos, the Broken Weaver)
  class BossWeaver extends EnemyBase {
    constructor(spawn) {
      super('boss', spawn.x, spawn.y, 56, 84, 420, 200);
      this.isBoss = true;
      this.name = '残丝监守者 · 维洛斯';
      this.subtitle = 'VELOS, THE BROKEN WEAVER';
      this.active = false; // 进入王座触发
      this.phase = 1;
      this.state = 'dormant'; // dormant | idle | dash_prep | dash | leap_prep | leap | slam | volley | sweep_prep | sweep | stagger
      this.stateTimer = 0;
      this.staggerAccum = 0;
      this.staggerThreshold = 135;
      this.attackIndex = 0;
      this.floorHazardTimer = 0;
      this.sweepWaves = [];
      this.afterimages = [];
    }

    awaken(world) {
      if (this.active || this.dead) return;
      this.active = true;
      this.state = 'idle';
      this.stateTimer = 1.0;
      world.level.setGateOpen('gate_boss_seal', false);
      world.audio.playBossRoar();
      world.audio.setBossMode(true);
      world.camera.shake(10, 0.5);
      world.particles.ring(this.cx, this.cy, Silkhollow.COLORS.corruptRed, 140);
      world.showLore(this.name, '古窟的丝线已然狂乱……亮出你的骨钉与渊丝吧！', 3.4);
    }

    takeDamage(dmg, hitDir, world, isCrit, isExecution) {
      if (this.dead || !this.active) return;
      this.hp -= dmg;
      this.hurtTimer = 0.14;

      if (isExecution) {
        // 处决后立刻结束失衡并大幅后跳重整态势
        this.state = 'idle';
        this.stateTimer = 0.95;
        this.staggerAccum = 0;
        this.vx = -(hitDir || 1) * 180;
        this.vy = -220;
      } else if (this.state !== 'stagger') {
        this.staggerAccum += dmg;
        if (this.staggerAccum >= this.staggerThreshold && this.hp > 0) {
          this.enterStagger(world);
        }
      }

      // 检测进入二阶段（< 55% HP）
      if (this.phase === 1 && this.hp > 0 && this.hp <= this.maxHp * 0.55) {
        this.enterPhase2(world);
      }

      if (this.hp <= 0) {
        this.die(world);
      }
    }

    enterPhase2(world) {
      this.phase = 2;
      this.state = 'idle';
      this.stateTimer = 1.05;
      this.vx = 0;
      this.vy = -120;
      world.level.activateBossPhase2Anchors(world);
      world.audio.playBossRoar();
      world.camera.shake(13, 0.55);
      world.particles.burst(this.cx, this.cy, 40, Silkhollow.COLORS.corruptRed, 380);
      world.particles.ring(this.cx, this.cy, Silkhollow.COLORS.silkCyan, 160);
      world.showLore('二阶段 · 渊丝暴走', '王座高空的渊丝环已全部觉醒！善用钩锁滞空躲避裂地腐潮！', 3.6);
    }

    enterStagger(world) {
      this.state = 'stagger';
      this.stateTimer = 3.8;
      this.staggerAccum = 0;
      this.vx = 0;
      this.floorHazardTimer = 0;
      world.audio.playClang();
      world.particles.ring(this.cx, this.cy, Silkhollow.COLORS.silkCyan, 90);
      world.showLore('失衡丝核暴露！', '立刻按下钩锁（右键 / E / K）拉扯维洛斯，触发「渊丝处决」！', 3.0);
    }

    die(world) {
      this.dead = true;
      this.active = false;
      this.floorHazardTimer = 0;
      world.player.shards += this.shardReward;
      world.level.setGateOpen('gate_boss_seal', true);
      world.audio.setBossMode(false);
      world.audio.playBossDeath();
      world.triggerHitstop(0.22);
      world.camera.shake(18, 0.8);
      world.particles.burst(this.cx, this.cy, 65, Silkhollow.COLORS.corruptOrange, 440);
      world.particles.burst(this.cx, this.cy, 45, Silkhollow.COLORS.silkBright, 360);
      world.particles.ring(this.cx, this.cy, Silkhollow.COLORS.paleWhite, 220);
      world.onBossDefeated();
    }

    chooseNextAttack(world) {
      const p1Cycle = ['dash_prep', 'leap_prep', 'volley'];
      const p2Cycle = ['sweep_prep', 'dash_prep', 'volley', 'leap_prep'];
      const list = this.phase === 1 ? p1Cycle : p2Cycle;
      const pick = list[this.attackIndex % list.length];
      this.attackIndex++;
      this.facing = world.player.cx >= this.cx ? 1 : -1;

      if (pick === 'dash_prep') {
        this.state = 'dash_prep';
        this.stateTimer = this.phase === 1 ? 0.56 : 0.44;
        this.vx = -this.facing * 85;
      } else if (pick === 'leap_prep') {
        this.state = 'leap_prep';
        this.stateTimer = this.phase === 1 ? 0.42 : 0.34;
        this.vx = 0;
      } else if (pick === 'volley') {
        this.state = 'volley';
        this.stateTimer = 1.25;
        this.volleyFired = 0;
        this.vx = 0;
      } else if (pick === 'sweep_prep') {
        this.state = 'sweep_prep';
        this.stateTimer = 1.05; // 充裕前摇让玩家钩锁上天！
        this.vx = 0;
        world.audio.playBossRoar();
      }
    }

    update(dt, world) {
      if (this.dead) return;
      this.animTime += dt;
      if (this.hurtTimer > 0) this.hurtTimer -= dt;
      if (this.floorHazardTimer > 0) this.floorHazardTimer -= dt;

      for (let i = this.afterimages.length - 1; i >= 0; i--) {
        this.afterimages[i].alpha -= dt * 3.8;
        if (this.afterimages[i].alpha <= 0) this.afterimages.splice(i, 1);
      }

      const arena = world.level.bossArena;
      if (!this.active) {
        if (world.player.cx > arena.triggerX) {
          this.awaken(world);
        }
        return;
      }

      // 更新地面冲击波
      for (let i = this.sweepWaves.length - 1; i >= 0; i--) {
        const wv = this.sweepWaves[i];
        wv.x += wv.vx * dt;
        wv.life -= dt;
        const wRect = { x: wv.x - wv.w * 0.5, y: wv.y - wv.h, w: wv.w, h: wv.h };
        if (Silkhollow.aabb(wRect, world.player)) {
          world.player.takeDamage(1, wv.x, world, false);
        }
        if (wv.life <= 0 || wv.x < arena.minX || wv.x > arena.maxX) {
          this.sweepWaves.splice(i, 1);
        }
      }

      // 二阶段全屏地面腐潮伤害判定（玩家站在地面会受伤，钩锁悬吊或二段跳安全！）
      if (this.floorHazardTimer > 0) {
        const floorBand = {
          x: arena.minX,
          y: arena.floorY - 38,
          w: arena.maxX - arena.minX,
          h: 38,
        };
        if (Silkhollow.aabb(floorBand, world.player)) {
          world.player.takeDamage(1, this.cx, world, false);
        }
      }

      // Boss 状态机
      const gravScale = this.state === 'volley' ? 0.15 : 1.0;
      this.vy += CFG.GRAVITY * gravScale * dt;

      if (this.state === 'idle') {
        this.vx *= 0.85;
        this.facing = world.player.cx >= this.cx ? 1 : -1;
        this.stateTimer -= dt;
        if (this.stateTimer <= 0) {
          this.chooseNextAttack(world);
        }
      } else if (this.state === 'dash_prep') {
        this.vx *= 0.9;
        this.stateTimer -= dt;
        if (this.stateTimer <= 0) {
          this.state = 'dash';
          this.stateTimer = 0.36;
          this.vx = this.facing * (this.phase === 1 ? 660 : 760);
          world.audio.playDash();
          world.camera.shake(6, 0.16);
        }
      } else if (this.state === 'dash') {
        this.stateTimer -= dt;
        if (Math.random() < 0.8) {
          this.afterimages.push({ x: this.x, y: this.y, facing: this.facing, alpha: 0.5 });
        }
        if (this.stateTimer <= 0) {
          this.state = 'idle';
          this.stateTimer = this.phase === 1 ? 0.72 : 0.52;
          this.vx *= 0.2;
        }
      } else if (this.state === 'leap_prep') {
        this.stateTimer -= dt;
        if (this.stateTimer <= 0) {
          this.state = 'leap';
          const targetX = Silkhollow.clamp(world.player.cx, arena.minX + 100, arena.maxX - 100);
          this.vx = Silkhollow.clamp((targetX - this.cx) * 1.35, -480, 480);
          this.vy = -720;
          world.audio.playJump(true);
        }
      } else if (this.state === 'leap') {
        if (this.vy > 0 && this.onGround) {
          // 重砸地面释放左右震裂冲击波
          this.state = 'idle';
          this.stateTimer = this.phase === 1 ? 0.85 : 0.62;
          this.vx = 0;
          world.camera.shake(11, 0.28);
          world.audio.playSlam();
          world.particles.burst(this.cx, arena.floorY, 24, Silkhollow.COLORS.corruptOrange, 310);
          const waveSpeed = this.phase === 1 ? 370 : 450;
          this.sweepWaves.push({ x: this.cx - 20, y: arena.floorY, vx: -waveSpeed, w: 34, h: 48, life: 2.2 });
          this.sweepWaves.push({ x: this.cx + 20, y: arena.floorY, vx: waveSpeed, w: 34, h: 48, life: 2.2 });
        }
      } else if (this.state === 'volley') {
        // 缓升滞空并依次发射 3 枚丝矛
        const desiredY = arena.floorY - 210;
        this.vy = (desiredY - this.y) * 3.8;
        this.vx *= 0.9;
        this.facing = world.player.cx >= this.cx ? 1 : -1;
        this.stateTimer -= dt;
        const shots = this.phase === 1 ? 3 : 4;
        const elapsed = 1.25 - this.stateTimer;
        if (this.volleyFired < shots && elapsed >= 0.25 + this.volleyFired * 0.24) {
          this.volleyFired++;
          const dx = world.player.cx - this.cx;
          const dy = world.player.cy - this.cy;
          const len = Math.hypot(dx, dy) || 1;
          const spd = this.phase === 1 ? 410 : 490;
          world.enemyProjectiles.push({
            x: this.cx + this.facing * 20,
            y: this.cy - 10,
            vx: (dx / len) * spd,
            vy: (dy / len) * spd,
            radius: 9,
            life: 2.5,
            isSpear: true,
            angle: Math.atan2(dy, dx),
            color: Silkhollow.COLORS.corruptRed,
          });
          world.audio.playSilkShoot();
        }
        if (this.stateTimer <= 0) {
          this.state = 'idle';
          this.stateTimer = this.phase === 1 ? 0.78 : 0.56;
        }
      } else if (this.state === 'sweep_prep') {
        this.vx *= 0.8;
        this.stateTimer -= dt;
        if (Math.random() < 0.6) {
          world.particles.spawn(
            arena.minX + Math.random() * (arena.maxX - arena.minX),
            arena.floorY - 4,
            0,
            -80 - Math.random() * 60,
            3,
            0.35,
            Silkhollow.COLORS.corruptRed
          );
        }
        if (this.stateTimer <= 0) {
          this.state = 'sweep';
          this.stateTimer = 1.35;
          this.floorHazardTimer = 1.35;
          world.camera.shake(12, 0.5);
          world.audio.playSlam();
        }
      } else if (this.state === 'sweep') {
        this.stateTimer -= dt;
        if (this.stateTimer <= 0) {
          this.state = 'idle';
          this.stateTimer = 0.85;
        }
      } else if (this.state === 'stagger') {
        this.vx *= 0.8;
        this.stateTimer -= dt;
        if (this.stateTimer <= 0) {
          this.state = 'idle';
          this.stateTimer = 0.65;
        }
      }

      this.moveSolid(dt, world.level);
      this.x = Silkhollow.clamp(this.x, arena.minX + 12, arena.maxX - this.w - 12);

      // 失衡状态不造成碰撞伤害，鼓励冲上去钩锁处决或挥砍
      if (this.state !== 'stagger') {
        this.checkPlayerContact(world.player, world);
      }
    }
  }

  Silkhollow.createEnemiesFromLevel = function (level) {
    nextEnemyId = 1;
    const list = [];
    for (const sp of level.enemySpawns) {
      if (sp.type === 'crawler') list.push(new Crawler(sp));
      else if (sp.type === 'wisp') list.push(new SporeWisp(sp));
      else if (sp.type === 'hopper') list.push(new MossHopper(sp));
      else if (sp.type === 'knight') list.push(new HuskKnight(sp));
      else if (sp.type === 'boss') list.push(new BossWeaver(sp));
    }
    return list;
  };
})(window);
