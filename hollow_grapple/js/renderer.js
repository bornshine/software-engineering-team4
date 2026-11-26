(function (global) {
  'use strict';

  const Silkhollow = (global.Silkhollow = global.Silkhollow || {});
  const TILE = Silkhollow.TILE;
  const TS = Silkhollow.TILE_SIZE;
  const C = Silkhollow.COLORS;

  class ParticleSystem {
    constructor() {
      this.particles = [];
      this.rings = [];
      this.motes = [];
      for (let i = 0; i < 55; i++) {
        this.motes.push({
          x: Math.random() * Silkhollow.VIEW_W,
          y: Math.random() * Silkhollow.VIEW_H,
          r: 1 + Math.random() * 2.2,
          speedY: -8 - Math.random() * 14,
          phase: Math.random() * Math.PI * 2,
          alpha: 0.15 + Math.random() * 0.4,
        });
      }
    }

    spawn(x, y, vx, vy, size, life, color) {
      if (this.particles.length > 360) return;
      this.particles.push({ x, y, vx, vy, size, life, maxLife: life, color });
    }

    burst(x, y, count, color, speed) {
      for (let i = 0; i < count; i++) {
        const ang = Math.random() * Math.PI * 2;
        const spd = (0.3 + Math.random() * 0.7) * (speed || 200);
        this.spawn(x, y, Math.cos(ang) * spd, Math.sin(ang) * spd, 2 + Math.random() * 3.2, 0.25 + Math.random() * 0.35, color);
      }
    }

    ring(x, y, color, maxRadius) {
      this.rings.push({ x, y, r: 6, maxR: maxRadius || 60, color, life: 0.34, maxLife: 0.34 });
    }

    update(dt) {
      for (let i = this.particles.length - 1; i >= 0; i--) {
        const p = this.particles[i];
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        p.vx *= 0.94;
        p.vy *= 0.94;
        p.life -= dt;
        if (p.life <= 0) this.particles.splice(i, 1);
      }
      for (let i = this.rings.length - 1; i >= 0; i--) {
        const r = this.rings[i];
        r.life -= dt;
        const t = 1 - r.life / r.maxLife;
        r.r = 6 + (r.maxR - 6) * (1 - Math.pow(1 - t, 3));
        if (r.life <= 0) this.rings.splice(i, 1);
      }
      for (const m of this.motes) {
        m.phase += dt * 1.4;
        m.y += m.speedY * dt;
        m.x += Math.sin(m.phase) * 10 * dt;
        if (m.y < -10) {
          m.y = Silkhollow.VIEW_H + 10;
          m.x = Math.random() * Silkhollow.VIEW_W;
        }
      }
    }
  }

  class Renderer {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.time = 0;
      this.bossHpTrail = 420;
    }

    render(world, dt) {
      this.time += dt;
      const ctx = this.ctx;
      const W = Silkhollow.VIEW_W;
      const H = Silkhollow.VIEW_H;
      const { level, player, enemies, particles, camera, currentZone } = world;

      ctx.clearRect(0, 0, W, H);

      // 1) 五层视差深渊背景
      this.drawParallaxBackground(ctx, W, H, camera, currentZone);

      // 进入世界坐标系（附带微震偏移）
      ctx.save();
      ctx.translate(-Math.round(camera.renderX), -Math.round(camera.renderY));

      // 2) 背景装饰（远古石柱、吊链、钟乳石、荧光蘑菇、晶簇）
      this.drawDecor(ctx, level, camera);

      // 3) 瓦片地形与尖刺（仅渲染视口可见范围）
      this.drawTiles(ctx, level, camera);

      // 4) 闸门、长椅、石碑、收集物、共鸣铃、渊丝环锚点
      this.drawGates(ctx, level);
      this.drawBenches(ctx, level, player);
      this.drawTablets(ctx, level);
      this.drawPickups(ctx, level);
      this.drawBells(ctx, level);
      this.drawAnchors(ctx, level);

      // 5) 敌怪与 Boss
      for (const e of enemies) {
        if (!e.dead) this.drawEnemy(ctx, e, level);
      }

      // 6) 敌人投射物与玩家灵魂脉冲弹
      this.drawProjectiles(ctx, world.enemyProjectiles, player.soulBolts);

      // 7) 渊丝瞄准锁环与实况钩锁丝线
      this.drawGrappleReticle(ctx, player);
      this.drawGrappleLine(ctx, player);

      // 8) 主角（残影 + Verlet 披风 + 苍白双角面具容器 + 骨钉斩弧）
      this.drawPlayer(ctx, player);

      // 9) 粒子与冲击波环
      this.drawParticles(ctx, particles);

      ctx.restore();

      // 10) 前景漂浮孢子、受击红晕与暗角氛围
      this.drawForegroundAtmosphere(ctx, W, H, particles, player, currentZone);

      // 11) 经典空洞骑士风 HUD（灵魂球 + 面具血条 + 微尘 + 迷雾小地图 + Boss 血条）
      this.drawHUD(ctx, W, H, world, dt);
    }

    drawParallaxBackground(ctx, W, H, camera, zone) {
      const grad = ctx.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0, '#050811');
      grad.addColorStop(0.55, zone ? zone.tint : '#101d32');
      grad.addColorStop(1, '#060a14');
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, W, H);

      // Layer 1 (0.10x): 洞顶微弱体积光柱
      ctx.save();
      const ox1 = -(camera.x * 0.1) % 340;
      for (let x = ox1 - 340; x < W + 340; x += 340) {
        const beamGrad = ctx.createLinearGradient(x, 0, x + 90, H * 0.85);
        beamGrad.addColorStop(0, zone ? zone.fog : 'rgba(94,234,212,0.05)');
        beamGrad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = beamGrad;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x + 120, 0);
        ctx.lineTo(x + 210, H);
        ctx.lineTo(x - 40, H);
        ctx.closePath();
        ctx.fill();
      }
      ctx.restore();

      // Layer 2 (0.24x): 远景哥特废墟拱门剪影
      ctx.save();
      ctx.fillStyle = 'rgba(8, 13, 25, 0.58)';
      const ox2 = -(camera.x * 0.24) % 280;
      const oy2 = -(camera.y * 0.12) % 220;
      for (let x = ox2 - 280; x < W + 280; x += 280) {
        // 石柱
        ctx.fillRect(x + 20, 0, 44, H);
        // 哥特尖拱顶
        ctx.beginPath();
        ctx.moveTo(x + 64, 160 + oy2 * 0.2);
        ctx.quadraticCurveTo(x + 160, 40 + oy2 * 0.2, x + 260, 160 + oy2 * 0.2);
        ctx.lineTo(x + 260, 0);
        ctx.lineTo(x + 64, 0);
        ctx.closePath();
        ctx.fill();
      }
      ctx.restore();

      // Layer 3 (0.45x): 中景悬垂钟乳石与远山岩脊
      ctx.save();
      ctx.fillStyle = 'rgba(12, 19, 34, 0.65)';
      const ox3 = -(camera.x * 0.45) % 220;
      for (let x = ox3 - 220; x < W + 220; x += 220) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x + 36, 0);
        ctx.lineTo(x + 18, 95 + ((Math.abs(Math.floor(x)) * 17) % 60));
        ctx.closePath();
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(x + 110, H);
        ctx.lineTo(x + 175, H);
        ctx.lineTo(x + 142, H - 110);
        ctx.closePath();
        ctx.fill();
      }
      ctx.restore();
    }

    drawDecor(ctx, level, camera) {
      const minX = camera.x - 100;
      const maxX = camera.x + Silkhollow.VIEW_W + 100;
      for (const d of level.decor) {
        if (d.x < minX || d.x > maxX) continue;
        if (d.kind === 'stalactite') {
          ctx.fillStyle = d.color;
          ctx.beginPath();
          ctx.moveTo(d.x - 12, d.y);
          ctx.lineTo(d.x + 12, d.y);
          ctx.lineTo(d.x, d.y + d.len);
          ctx.closePath();
          ctx.fill();
        } else if (d.kind === 'chain') {
          ctx.strokeStyle = 'rgba(130, 145, 195, 0.35)';
          ctx.lineWidth = 2;
          ctx.setLineDash([6, 4]);
          ctx.beginPath();
          ctx.moveTo(d.x, d.y);
          ctx.lineTo(d.x, d.y + d.len);
          ctx.stroke();
          ctx.setLineDash([]);
        } else if (d.kind === 'pillar') {
          ctx.fillStyle = 'rgba(26, 28, 52, 0.65)';
          ctx.fillRect(d.x - 18, d.y - d.h, 36, d.h);
          ctx.strokeStyle = 'rgba(139, 147, 201, 0.2)';
          ctx.lineWidth = 1.5;
          ctx.strokeRect(d.x - 18, d.y - d.h, 36, d.h);
        } else if (d.kind === 'mushroom') {
          const glow = 0.6 + 0.3 * Math.sin(this.time * 2.5 + d.x);
          ctx.fillStyle = '#1b3a3a';
          ctx.fillRect(d.x - 2, d.y - d.size * 0.9, 4, d.size * 0.9);
          ctx.fillStyle = d.hue;
          ctx.globalAlpha = 0.22 * glow;
          ctx.beginPath();
          ctx.arc(d.x, d.y - d.size, d.size * 1.6, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = 0.88;
          ctx.beginPath();
          ctx.arc(d.x, d.y - d.size * 0.85, d.size * 0.75, Math.PI, 0);
          ctx.fill();
          ctx.globalAlpha = 1;
        } else if (d.kind === 'crystal') {
          ctx.fillStyle = d.color;
          ctx.globalAlpha = 0.45;
          ctx.beginPath();
          ctx.moveTo(d.x - d.size * 0.5, d.y);
          ctx.lineTo(d.x, d.y - d.size * 1.4);
          ctx.lineTo(d.x + d.size * 0.5, d.y);
          ctx.closePath();
          ctx.fill();
          ctx.globalAlpha = 1;
        }
      }
    }

    drawTiles(ctx, level, camera) {
      const startX = Math.max(0, Math.floor(camera.x / TS) - 1);
      const endX = Math.min(level.cols - 1, Math.ceil((camera.x + Silkhollow.VIEW_W) / TS) + 1);
      const startY = Math.max(0, Math.floor(camera.y / TS) - 1);
      const endY = Math.min(level.rows - 1, Math.ceil((camera.y + Silkhollow.VIEW_H) / TS) + 1);

      for (let ty = startY; ty <= endY; ty++) {
        for (let tx = startX; tx <= endX; tx++) {
          const t = level.grid[ty][tx];
          if (t === TILE.EMPTY) continue;
          const x = tx * TS;
          const y = ty * TS;

          if (t === TILE.STONE || t === TILE.MOSS || t === TILE.TEMPLE) {
            const dark = t === TILE.MOSS ? C.mossDark : t === TILE.TEMPLE ? C.templeDark : C.stoneDark;
            const base = t === TILE.MOSS ? C.mossBase : t === TILE.TEMPLE ? C.templeBase : C.stoneBase;
            const edge = t === TILE.MOSS ? C.mossEdge : t === TILE.TEMPLE ? C.templeEdge : C.stoneEdge;

            ctx.fillStyle = dark;
            ctx.fillRect(x, y, TS, TS);

            // 砖纹细节
            if ((tx + ty) % 2 === 0) {
              ctx.fillStyle = base;
              ctx.fillRect(x + 2, y + 2, TS - 4, TS - 4);
            }

            // 依据相邻空格渲染高光边缘（大幅提升手绘立体感）
            const topAir = !level.isSolidTile(tx, ty - 1);
            const botAir = !level.isSolidTile(tx, ty + 1);
            const leftAir = !level.isSolidTile(tx - 1, ty);
            const rightAir = !level.isSolidTile(tx + 1, ty);

            if (topAir) {
              ctx.fillStyle = edge;
              ctx.fillRect(x, y, TS, t === TILE.MOSS ? 5 : 4);
              if (t === TILE.MOSS) {
                // 垂落荧光苔须
                ctx.fillStyle = 'rgba(52, 211, 153, 0.55)';
                ctx.fillRect(x + 6, y + 5, 4, 6);
                ctx.fillRect(x + 24, y + 5, 3, 9);
              }
            }
            if (botAir) {
              ctx.fillStyle = 'rgba(0,0,0,0.45)';
              ctx.fillRect(x, y + TS - 4, TS, 4);
            }
            if (leftAir) {
              ctx.fillStyle = 'rgba(186, 230, 253, 0.18)';
              ctx.fillRect(x, y, 3, TS);
            }
            if (rightAir) {
              ctx.fillStyle = 'rgba(186, 230, 253, 0.14)';
              ctx.fillRect(x + TS - 3, y, 3, TS);
            }
          } else if (t === TILE.PLATFORM) {
            ctx.fillStyle = '#314466';
            ctx.fillRect(x, y, TS, 10);
            ctx.fillStyle = '#7dd3fc';
            ctx.globalAlpha = 0.65;
            ctx.fillRect(x, y, TS, 2.5);
            ctx.globalAlpha = 1;
            // 底部装饰托架
            ctx.fillStyle = '#1b2842';
            ctx.fillRect(x + 6, y + 10, 4, 5);
            ctx.fillRect(x + TS - 10, y + 10, 4, 5);
          } else if (t === TILE.SPIKE_UP) {
            // 锋利黑曜晶刺（可下劈弹反！）
            const count = 3;
            const sw = TS / count;
            for (let i = 0; i < count; i++) {
              const sx = x + i * sw;
              ctx.fillStyle = '#2d1c2e';
              ctx.beginPath();
              ctx.moveTo(sx + 1, y + TS);
              ctx.lineTo(sx + sw * 0.5, y + 8);
              ctx.lineTo(sx + sw - 1, y + TS);
              ctx.closePath();
              ctx.fill();

              // 锐利橙白尖刺高光
              ctx.strokeStyle = '#fda4af';
              ctx.lineWidth = 1.4;
              ctx.beginPath();
              ctx.moveTo(sx + sw * 0.5, y + 8);
              ctx.lineTo(sx + sw - 2, y + TS - 2);
              ctx.stroke();
            }
          }
        }
      }
    }

    drawGates(ctx, level) {
      for (const g of level.gates) {
        const visibleH = g.h * (1 - g.openProgress);
        if (visibleH <= 2) continue;
        const isBossSeal = g.id === 'gate_boss_seal';

        ctx.save();
        if (isBossSeal) {
          // 渊丝猩红光栅封印
          ctx.fillStyle = 'rgba(244, 63, 94, 0.25)';
          ctx.fillRect(g.x + 8, g.y, g.w - 16, visibleH);
          ctx.strokeStyle = C.corruptRed;
          ctx.lineWidth = 3;
          ctx.beginPath();
          ctx.moveTo(g.x + g.w * 0.5, g.y);
          ctx.lineTo(g.x + g.w * 0.5, g.y + visibleH);
          ctx.stroke();
        } else {
          // 雕刻青铜石闸门
          ctx.fillStyle = '#28314f';
          ctx.fillRect(g.x + 4, g.y, g.w - 8, visibleH);
          ctx.strokeStyle = '#94a3c8';
          ctx.lineWidth = 2;
          ctx.strokeRect(g.x + 4, g.y, g.w - 8, visibleH);
          // 符文光纹
          ctx.fillStyle = '#fbbf24';
          for (let ry = g.y + 20; ry < g.y + visibleH - 12; ry += 32) {
            ctx.beginPath();
            ctx.arc(g.x + g.w * 0.5, ry, 4, 0, Math.PI * 2);
            ctx.fill();
          }
        }
        ctx.restore();
      }
    }

    drawBenches(ctx, level, player) {
      for (const b of level.benches) {
        const x = b.x;
        const y = b.y;
        // 温暖微光灯柱
        const lanternX = x + 36;
        const lanternY = y - 54;
        const glow = ctx.createRadialGradient(lanternX, lanternY, 4, lanternX, lanternY, 90);
        glow.addColorStop(0, 'rgba(186, 230, 253, 0.34)');
        glow.addColorStop(0.5, 'rgba(94, 234, 212, 0.11)');
        glow.addColorStop(1, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(lanternX, lanternY, 90, 0, Math.PI * 2);
        ctx.fill();

        // 灯柱杆
        ctx.strokeStyle = '#64748b';
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(lanternX, y);
        ctx.lineTo(lanternX, lanternY);
        ctx.stroke();
        ctx.fillStyle = '#f0f9ff';
        ctx.beginPath();
        ctx.arc(lanternX, lanternY, 6, 0, Math.PI * 2);
        ctx.fill();

        // 铁艺古窟长椅
        ctx.strokeStyle = '#94a3b8';
        ctx.lineWidth = 3;
        ctx.fillStyle = '#1e293b';
        // 靠背弧线
        ctx.beginPath();
        ctx.roundRect(x - 26, y - 28, 52, 12, 4);
        ctx.fill();
        ctx.stroke();
        // 座面与椅腿
        ctx.fillRect(x - 28, y - 14, 56, 5);
        ctx.beginPath();
        ctx.moveTo(x - 22, y - 14); ctx.lineTo(x - 24, y);
        ctx.moveTo(x + 22, y - 14); ctx.lineTo(x + 24, y);
        ctx.stroke();

        // 靠近时显示交互提示
        if (Silkhollow.dist(player.cx, player.cy, x, y - 18) < 75) {
          ctx.fillStyle = '#e0f2fe';
          ctx.font = '12px "Microsoft YaHei", sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('[W / ↑] 歇息存档', x, y - 44);
        }
      }
    }

    drawTablets(ctx, level) {
      for (const t of level.tablets) {
        const x = t.x;
        const y = t.y;
        ctx.fillStyle = '#253452';
        ctx.beginPath();
        ctx.moveTo(x - 16, y);
        ctx.lineTo(x - 13, y - 48);
        ctx.lineTo(x, y - 58);
        ctx.lineTo(x + 13, y - 48);
        ctx.lineTo(x + 16, y);
        ctx.closePath();
        ctx.fill();
        ctx.strokeStyle = '#64748b';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // 发光刻痕
        const a = 0.55 + 0.35 * Math.sin(this.time * 2.4 + x);
        ctx.strokeStyle = `rgba(94, 234, 212, ${a})`;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(x - 6, y - 38); ctx.lineTo(x + 6, y - 38);
        ctx.moveTo(x - 7, y - 28); ctx.lineTo(x + 7, y - 28);
        ctx.moveTo(x - 4, y - 18); ctx.lineTo(x + 4, y - 18);
        ctx.stroke();
      }
    }

    drawPickups(ctx, level) {
      for (const p of level.pickups) {
        if (p.collected) continue;
        const py = p.y + Math.sin(p.bob) * 6;
        ctx.save();
        if (p.type === 'silk_wings') {
          const glow = ctx.createRadialGradient(p.x, py, 4, p.x, py, 48);
          glow.addColorStop(0, 'rgba(204, 251, 241, 0.75)');
          glow.addColorStop(0.5, 'rgba(94, 234, 212, 0.25)');
          glow.addColorStop(1, 'rgba(0,0,0,0)');
          ctx.fillStyle = glow;
          ctx.beginPath();
          ctx.arc(p.x, py, 48, 0, Math.PI * 2);
          ctx.fill();

          // 苍白双翼造型
          ctx.strokeStyle = C.paleWhite;
          ctx.fillStyle = 'rgba(204, 251, 241, 0.85)';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(p.x, py + 4);
          ctx.quadraticCurveTo(p.x - 24, py - 18, p.x - 28, py + 2);
          ctx.quadraticCurveTo(p.x - 14, py + 10, p.x, py + 4);
          ctx.quadraticCurveTo(p.x + 24, py - 18, p.x + 28, py + 2);
          ctx.quadraticCurveTo(p.x + 14, py + 10, p.x, py + 4);
          ctx.fill();
          ctx.stroke();
        } else if (p.type === 'mask_shard') {
          const glow = ctx.createRadialGradient(p.x, py, 3, p.x, py, 38);
          glow.addColorStop(0, 'rgba(244, 248, 255, 0.8)');
          glow.addColorStop(0.6, 'rgba(192, 132, 252, 0.26)');
          glow.addColorStop(1, 'rgba(0,0,0,0)');
          ctx.fillStyle = glow;
          ctx.beginPath();
          ctx.arc(p.x, py, 38, 0, Math.PI * 2);
          ctx.fill();

          ctx.fillStyle = C.paleWhite;
          ctx.beginPath();
          ctx.ellipse(p.x, py, 11, 14, 0, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = '#070a14';
          ctx.beginPath();
          ctx.arc(p.x - 4, py + 1, 2.2, 0, Math.PI * 2);
          ctx.arc(p.x + 4, py + 1, 2.2, 0, Math.PI * 2);
          ctx.fill();
        } else {
          // 苍白微尘晶体
          ctx.fillStyle = C.paleBlue;
          ctx.shadowColor = C.silkCyan;
          ctx.shadowBlur = 10;
          ctx.beginPath();
          ctx.moveTo(p.x, py - 9);
          ctx.lineTo(p.x + 7, py);
          ctx.lineTo(p.x, py + 9);
          ctx.lineTo(p.x - 7, py);
          ctx.closePath();
          ctx.fill();
        }
        ctx.restore();
      }
    }

    drawBells(ctx, level) {
      for (const b of level.bells) {
        const swing = b.ringAnim > 0 ? Math.sin(this.time * 28) * 0.35 * b.ringAnim : Math.sin(this.time * 1.6) * 0.04;
        ctx.save();
        ctx.translate(b.x, b.y - 16);
        ctx.rotate(swing);

        // 悬绳
        ctx.strokeStyle = '#94a3b8';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(0, -32);
        ctx.lineTo(0, 0);
        ctx.stroke();

        // 光晕
        const glowColor = b.triggered ? 'rgba(94, 234, 212, 0.35)' : 'rgba(251, 191, 36, 0.35)';
        ctx.fillStyle = glowColor;
        ctx.beginPath();
        ctx.arc(0, 14, 28, 0, Math.PI * 2);
        ctx.fill();

        // 铃身
        ctx.fillStyle = b.triggered ? '#5eead4' : '#f59e0b';
        ctx.strokeStyle = '#fef3c7';
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.moveTo(-11, 24);
        ctx.quadraticCurveTo(-12, 4, 0, 2);
        ctx.quadraticCurveTo(12, 4, 11, 24);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // 铃锤
        ctx.fillStyle = '#fffbeb';
        ctx.beginPath();
        ctx.arc(0, 26, 3.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    }

    drawAnchors(ctx, level) {
      for (const a of level.anchors) {
        ctx.save();
        ctx.translate(a.x, a.y);
        if (!a.active) {
          // 休眠丝环（Boss 二阶段前暗淡待唤醒）
          ctx.strokeStyle = 'rgba(100, 116, 139, 0.35)';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(0, 0, 11, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
          continue;
        }

        const pulse = 1 + Math.sin(a.pulse) * 0.14;
        const glow = ctx.createRadialGradient(0, 0, 2, 0, 0, 28 * pulse);
        glow.addColorStop(0, 'rgba(204, 251, 241, 0.72)');
        glow.addColorStop(0.45, 'rgba(94, 234, 212, 0.25)');
        glow.addColorStop(1, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(0, 0, 28 * pulse, 0, Math.PI * 2);
        ctx.fill();

        // 旋转外环
        ctx.rotate(this.time * 1.4);
        ctx.strokeStyle = C.silkCyan;
        ctx.lineWidth = 2.2;
        ctx.setLineDash([7, 5]);
        ctx.beginPath();
        ctx.arc(0, 0, 13, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);

        // 核心星芒
        ctx.fillStyle = C.silkBright;
        ctx.beginPath();
        ctx.arc(0, 0, 4.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    }

    drawGrappleReticle(ctx, player) {
      const t = player.bestTarget;
      if (!t || player.grapple.state !== 'idle') return;

      ctx.save();
      ctx.translate(t.x, t.y);
      const isExec = t.isExec;
      const col = isExec ? C.corruptGold : t.type === 'enemy' ? C.corruptOrange : t.type === 'bell' ? '#fde047' : C.silkBright;

      // 细虚线预瞄丝线
      ctx.save();
      ctx.translate(-t.x, -t.y);
      ctx.strokeStyle = isExec ? 'rgba(253, 224, 71, 0.45)' : 'rgba(94, 234, 212, 0.24)';
      ctx.lineWidth = isExec ? 2 : 1.2;
      ctx.setLineDash([5, 6]);
      ctx.beginPath();
      ctx.moveTo(player.cx, player.cy);
      ctx.lineTo(t.x, t.y);
      ctx.stroke();
      ctx.restore();

      // 动态旋转锁定外框
      const rad = (isExec ? 34 : 21) + Math.sin(this.time * 9) * 2.5;
      ctx.rotate(-this.time * (isExec ? 4.2 : 2.2));
      ctx.strokeStyle = col;
      ctx.lineWidth = isExec ? 3 : 2;
      for (let i = 0; i < 4; i++) {
        ctx.rotate(Math.PI * 0.5);
        ctx.beginPath();
        ctx.arc(0, 0, rad, -0.35, 0.35);
        ctx.stroke();
      }

      if (isExec) {
        ctx.rotate(this.time * 4.2);
        ctx.fillStyle = C.corruptGold;
        ctx.font = 'bold 12px "Microsoft YaHei", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('渊丝处决 [右键/E/K]', 0, -rad - 10);
      }
      ctx.restore();
    }

    drawGrappleLine(ctx, player) {
      const g = player.grapple;
      if (g.state === 'idle') return;

      const x1 = player.cx;
      const y1 = player.cy;
      const x2 = g.state === 'shooting' ? g.tipX : g.anchorX;
      const y2 = g.state === 'shooting' ? g.tipY : g.anchorY;
      const dx = x2 - x1;
      const dy = y2 - y1;
      const dist = Math.hypot(dx, dy) || 1;
      const nx = -dy / dist;
      const ny = dx / dist;

      ctx.save();
      // 外层青白发光丝晕
      ctx.strokeStyle = 'rgba(94, 234, 212, 0.42)';
      ctx.lineWidth = 6;
      ctx.lineCap = 'round';
      ctx.beginPath();
      const segs = 14;
      for (let i = 0; i <= segs; i++) {
        const f = i / segs;
        const env = Math.sin(f * Math.PI);
        const wave = Math.sin(f * 14 - this.time * 36) * g.waveAmp * env;
        const px = x1 + dx * f + nx * wave;
        const py = y1 + dy * f + ny * wave;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();

      // 内层锐利苍白主丝
      ctx.strokeStyle = C.silkBright;
      ctx.lineWidth = 2.2;
      ctx.stroke();

      // 丝针尖端菱形光点
      ctx.fillStyle = C.paleWhite;
      ctx.beginPath();
      ctx.arc(x2, y2, 4.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    drawPlayer(ctx, player) {
      // 1) 冲刺 / 钩锁白色残影
      for (const a of player.afterimages) {
        ctx.save();
        ctx.globalAlpha = a.alpha * 0.55;
        ctx.fillStyle = a.tint || C.paleBlue;
        ctx.beginPath();
        ctx.ellipse(a.x + player.w * 0.5, a.y + player.h * 0.5, 11, 18, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      const blink = player.invulnTimer > 0 && Math.floor(this.time * 24) % 2 === 0;
      ctx.save();
      if (blink) ctx.globalAlpha = 0.45;

      // 2) Verlet 物理柔性披风
      ctx.beginPath();
      const c0 = player.cloak[0];
      ctx.moveTo(c0.x - 8, c0.y);
      for (let i = 1; i < player.cloak.length; i++) {
        const p = player.cloak[i];
        ctx.lineTo(p.x - 6 - i * 1.1, p.y);
      }
      for (let i = player.cloak.length - 1; i >= 1; i--) {
        const p = player.cloak[i];
        ctx.lineTo(p.x + 6 + i * 1.1, p.y);
      }
      ctx.lineTo(c0.x + 8, c0.y);
      ctx.closePath();
      ctx.fillStyle = '#25314d';
      ctx.fill();
      ctx.strokeStyle = player.hookEmpowerTimer > 0 ? C.silkCyan : '#64748b';
      ctx.lineWidth = 1.6;
      ctx.stroke();

      // 3) 角色主体（带挤压拉伸形变）
      ctx.translate(player.cx, player.y + player.h);
      ctx.scale(player.facing * player.squashX, player.squashY);

      // 黑暗虚空身躯与小脚
      ctx.fillStyle = '#090d18';
      ctx.fillRect(-6, -24, 12, 20);
      const runCycle = player.onGround && Math.abs(player.vx) > 25 ? Math.sin(player.animTime * 16) * 4 : 0;
      ctx.fillRect(-5 + runCycle, -6, 4, 6);
      ctx.fillRect(1 - runCycle, -6, 4, 6);

      // 象牙白双角面具（经典空洞骑士神韵！）
      ctx.fillStyle = player.hurtFlash > 0 ? '#fecdd3' : C.paleWhite;
      ctx.shadowColor = player.hookEmpowerTimer > 0 ? C.silkCyan : 'rgba(186, 230, 253, 0.35)';
      ctx.shadowBlur = player.hookEmpowerTimer > 0 ? 14 : 6;

      // 面具轮廓 + 弯曲双角
      ctx.beginPath();
      ctx.moveTo(-10, -24);
      ctx.quadraticCurveTo(-12, -37, -7, -45); // 左角尖
      ctx.quadraticCurveTo(-3, -38, 0, -37);   // 额中凹槽
      ctx.quadraticCurveTo(3, -38, 8, -46);    // 右角尖
      ctx.quadraticCurveTo(12, -36, 10, -24);
      ctx.quadraticCurveTo(0, -18, -10, -24);
      ctx.closePath();
      ctx.fill();
      ctx.shadowBlur = 0;

      // 漆黑空洞双眼
      ctx.fillStyle = '#06080f';
      ctx.beginPath();
      ctx.ellipse(-2.5, -28.5, 2.3, 3.6, -0.08, 0, Math.PI * 2);
      ctx.ellipse(4.8, -28.5, 2.4, 3.6, 0.08, 0, Math.PI * 2);
      ctx.fill();

      // 背负的苍白骨钉
      ctx.strokeStyle = player.hookEmpowerTimer > 0 ? C.silkBright : '#cbd5e1';
      ctx.lineWidth = 2.4;
      ctx.beginPath();
      ctx.moveTo(-12, -10);
      ctx.lineTo(10, -26);
      ctx.stroke();

      ctx.restore();

      // 4) 凝聚回血环形光效
      if (player.isFocusing) {
        ctx.save();
        ctx.strokeStyle = C.paleWhite;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(player.cx, player.cy, 28, -Math.PI * 0.5, -Math.PI * 0.5 + Math.PI * 2 * player.focusProgress);
        ctx.stroke();
        ctx.fillStyle = 'rgba(244, 248, 255, 0.14)';
        ctx.beginPath();
        ctx.arc(player.cx, player.cy, 26, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      if (player.healBurstTimer > 0) {
        ctx.save();
        ctx.globalAlpha = player.healBurstTimer;
        ctx.strokeStyle = C.silkBright;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(player.cx, player.cy, 38 * (1 - player.healBurstTimer * 0.5), 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }

      // 5) 骨钉四向弯月斩弧
      if (player.slash) {
        const s = player.slash;
        const t = 1 - s.timer / s.duration;
        ctx.save();
        ctx.translate(player.cx, player.cy);
        let rot = 0;
        if (s.dir === 'left') rot = Math.PI;
        else if (s.dir === 'up') rot = -Math.PI * 0.5;
        else if (s.dir === 'down') rot = Math.PI * 0.5;
        ctx.rotate(rot);

        const r = s.empowered ? 66 : 54;
        const alpha = 1 - t * 0.75;
        ctx.globalAlpha = alpha;
        ctx.fillStyle = s.empowered ? C.silkCyan : C.paleWhite;
        ctx.shadowColor = s.empowered ? C.silkCyan : C.paleBlue;
        ctx.shadowBlur = s.empowered ? 20 : 12;

        ctx.beginPath();
        ctx.arc(8, 0, r, -0.95, 0.95);
        ctx.arc(-4, 0, r * 0.76, 0.85, -0.85, true);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }
    }

    drawEnemy(ctx, e, level) {
      ctx.save();
      const hurt = e.hurtTimer > 0;

      if (e.type === 'crawler') {
        ctx.translate(e.cx, e.y + e.h);
        ctx.scale(e.facing, 1);
        ctx.fillStyle = hurt ? '#ffffff' : '#31253a';
        ctx.beginPath();
        ctx.ellipse(0, -10, 17, 11, 0, Math.PI, 0);
        ctx.fill();
        ctx.strokeStyle = '#fb923c';
        ctx.lineWidth = 1.6;
        ctx.stroke();
        // 腐化橙眼与背刺
        ctx.fillStyle = C.corruptOrange;
        ctx.beginPath();
        ctx.arc(10, -10, 2.8, 0, Math.PI * 2);
        ctx.fill();
      } else if (e.type === 'wisp') {
        const bob = Math.sin(e.animTime * 4) * 3;
        ctx.translate(e.cx, e.cy + bob);
        // 发光孢子幽灵外晕
        const glow = ctx.createRadialGradient(0, 0, 4, 0, 0, 30);
        glow.addColorStop(0, hurt ? 'rgba(255,255,255,0.85)' : 'rgba(251,146,60,0.65)');
        glow.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(0, 0, 30, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = hurt ? '#ffffff' : '#4a2130';
        ctx.beginPath();
        ctx.arc(0, -2, 13, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = C.corruptOrange;
        ctx.lineWidth = 2;
        ctx.stroke();
        // 发光眼
        ctx.fillStyle = C.corruptGold;
        ctx.beginPath();
        ctx.arc(-4, -2, 2.5, 0, Math.PI * 2);
        ctx.arc(4, -2, 2.5, 0, Math.PI * 2);
        ctx.fill();
      } else if (e.type === 'hopper') {
        ctx.translate(e.cx, e.y + e.h);
        ctx.scale(e.facing, e.telegraph > 0 ? 0.78 : 1);
        ctx.fillStyle = hurt ? '#ffffff' : '#1f3a36';
        ctx.beginPath();
        ctx.ellipse(0, -14, 16, 13, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#34d399';
        ctx.lineWidth = 1.8;
        ctx.stroke();
        ctx.fillStyle = C.corruptOrange;
        ctx.beginPath();
        ctx.arc(8, -16, 3, 0, Math.PI * 2);
        ctx.fill();
      } else if (e.type === 'knight') {
        ctx.translate(e.cx, e.y + e.h);
        ctx.scale(e.facing, 1);
        // 重甲披风与身躯
        ctx.fillStyle = hurt ? '#ffffff' : '#262942';
        ctx.fillRect(-15, -46, 30, 42);
        // 尖角面具头盔
        ctx.fillStyle = hurt ? '#ffffff' : '#cbd5e1';
        ctx.beginPath();
        ctx.moveTo(-12, -44);
        ctx.lineTo(-9, -60);
        ctx.lineTo(0, -52);
        ctx.lineTo(9, -60);
        ctx.lineTo(12, -44);
        ctx.closePath();
        ctx.fill();
        // 琥珀侵蚀双目
        ctx.fillStyle = C.corruptOrange;
        ctx.fillRect(2, -50, 5, 3.5);
        // 正面厚重青铜盾（巡逻时举在身前）
        if (e.state === 'patrol') {
          ctx.fillStyle = '#475569';
          ctx.strokeStyle = '#fde68a';
          ctx.lineWidth = 2;
          ctx.fillRect(10, -44, 10, 38);
          ctx.strokeRect(10, -44, 10, 38);
        } else if (e.state === 'windup') {
          // 蓄力高亮红光刀
          ctx.strokeStyle = C.corruptRed;
          ctx.lineWidth = 4;
          ctx.beginPath();
          ctx.moveTo(-12, -28);
          ctx.lineTo(-26, -54);
          ctx.stroke();
        } else if (e.state === 'lunge') {
          ctx.strokeStyle = C.corruptOrange;
          ctx.lineWidth = 5;
          ctx.beginPath();
          ctx.moveTo(8, -26);
          ctx.lineTo(44, -26);
          ctx.stroke();
        }
      } else if (e.isBoss) {
        this.drawBoss(ctx, e, level);
      }

      // 常规敌人头顶微型血条（受伤后显示）
      if (!e.isBoss && e.hp < e.maxHp) {
        ctx.restore();
        ctx.save();
        const bw = 36;
        const bx = e.cx - bw * 0.5;
        const by = e.y - 12;
        ctx.fillStyle = 'rgba(6, 9, 19, 0.75)';
        ctx.fillRect(bx, by, bw, 4);
        ctx.fillStyle = C.corruptOrange;
        ctx.fillRect(bx, by, bw * Math.max(0, e.hp / e.maxHp), 4);
      }
      ctx.restore();
    }

    drawBoss(ctx, boss, level) {
      const arena = level.bossArena;

      // 二阶段全屏地面腐潮预警与烈焰
      if (boss.state === 'sweep_prep') {
        const pulse = 0.25 + 0.35 * Math.sin(this.time * 24);
        ctx.fillStyle = `rgba(244, 63, 94, ${pulse})`;
        ctx.fillRect(arena.minX, arena.floorY - 22, arena.maxX - arena.minX, 22);
      } else if (boss.floorHazardTimer > 0) {
        const g = ctx.createLinearGradient(0, arena.floorY - 46, 0, arena.floorY);
        g.addColorStop(0, 'rgba(244, 63, 94, 0)');
        g.addColorStop(0.5, 'rgba(251, 146, 60, 0.85)');
        g.addColorStop(1, '#fef08a');
        ctx.fillStyle = g;
        ctx.fillRect(arena.minX, arena.floorY - 46, arena.maxX - arena.minX, 46);
      }

      // 地面冲击波
      for (const wv of boss.sweepWaves) {
        ctx.fillStyle = C.corruptOrange;
        ctx.shadowColor = C.corruptRed;
        ctx.shadowBlur = 14;
        ctx.beginPath();
        ctx.moveTo(wv.x - wv.w * 0.5, wv.y);
        ctx.quadraticCurveTo(wv.x, wv.y - wv.h * 1.4, wv.x + wv.w * 0.5, wv.y);
        ctx.closePath();
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      // Boss 残影
      for (const a of boss.afterimages) {
        ctx.save();
        ctx.globalAlpha = a.alpha * 0.45;
        ctx.fillStyle = boss.phase === 2 ? C.corruptRed : C.corruptOrange;
        ctx.fillRect(a.x, a.y, boss.w, boss.h);
        ctx.restore();
      }

      // Boss 本体：高大威严的「残丝监守者 · 维洛斯」
      ctx.save();
      ctx.translate(boss.cx, boss.y + boss.h);
      const kneelY = boss.state === 'stagger' ? 14 : 0;
      ctx.translate(0, kneelY);
      ctx.scale(boss.facing, 1);

      const hurt = boss.hurtTimer > 0;
      // 破碎猩红深黑长披风
      ctx.fillStyle = hurt ? '#ffffff' : boss.phase === 2 ? '#3d1022' : '#261428';
      ctx.beginPath();
      ctx.moveTo(-26, -72);
      ctx.lineTo(22, -72);
      ctx.lineTo(34, -4);
      ctx.lineTo(-32, -4);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = boss.phase === 2 ? C.corruptRed : C.corruptOrange;
      ctx.lineWidth = 2.4;
      ctx.stroke();

      // 冠冕双角苍白破损面具
      ctx.fillStyle = hurt ? '#ffffff' : '#f1f5f9';
      ctx.beginPath();
      ctx.moveTo(-18, -68);
      ctx.lineTo(-22, -98);
      ctx.lineTo(-8, -82);
      ctx.lineTo(0, -92);
      ctx.lineTo(8, -82);
      ctx.lineTo(22, -98);
      ctx.lineTo(18, -68);
      ctx.quadraticCurveTo(0, -56, -18, -68);
      ctx.closePath();
      ctx.fill();

      // 狂化发光双目
      ctx.fillStyle = boss.phase === 2 ? C.corruptRed : C.corruptOrange;
      ctx.shadowColor = C.corruptOrange;
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.ellipse(5, -72, 4, 2.5, 0.2, 0, Math.PI * 2);
      ctx.ellipse(-6, -72, 3.5, 2.5, -0.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      // 织渊长骨矛（蓄力时炽烈发光）
      const prepGlow = boss.state === 'dash_prep' || boss.state === 'dash';
      ctx.strokeStyle = prepGlow ? C.corruptGold : '#e2e8f0';
      ctx.lineWidth = prepGlow ? 5 : 3.5;
      ctx.beginPath();
      if (boss.state === 'dash_prep') {
        ctx.moveTo(-36, -42);
        ctx.lineTo(36, -42);
      } else if (boss.state === 'dash') {
        ctx.moveTo(-14, -42);
        ctx.lineTo(74, -42);
      } else {
        ctx.moveTo(-22, -16);
        ctx.lineTo(34, -76);
      }
      ctx.stroke();

      // 失衡暴露的青金「丝核」！！
      if (boss.state === 'stagger') {
        const coreR = 12 + Math.sin(this.time * 16) * 3;
        ctx.fillStyle = C.silkCyan;
        ctx.shadowColor = C.corruptGold;
        ctx.shadowBlur = 22;
        ctx.beginPath();
        ctx.arc(0, -44, coreR, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(0, -44, coreR * 0.45, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    drawProjectiles(ctx, enemyProj, soulBolts) {
      // 敌方腐化孢子 / Boss 丝矛
      for (const p of enemyProj) {
        ctx.save();
        ctx.translate(p.x, p.y);
        if (p.isSpear) {
          ctx.rotate(p.angle);
          ctx.strokeStyle = C.corruptRed;
          ctx.shadowColor = C.corruptOrange;
          ctx.shadowBlur = 14;
          ctx.lineWidth = 4;
          ctx.beginPath();
          ctx.moveTo(-22, 0);
          ctx.lineTo(20, 0);
          ctx.stroke();
          ctx.fillStyle = '#fef08a';
          ctx.beginPath();
          ctx.moveTo(24, 0);
          ctx.lineTo(12, -5);
          ctx.lineTo(12, 5);
          ctx.closePath();
          ctx.fill();
        } else {
          ctx.fillStyle = p.color;
          ctx.shadowColor = p.color;
          ctx.shadowBlur = 12;
          ctx.beginPath();
          ctx.arc(0, 0, p.radius, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = '#fff7ed';
          ctx.beginPath();
          ctx.arc(0, 0, p.radius * 0.45, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      }

      // 玩家苍白灵魂脉冲弹
      for (const b of soulBolts) {
        ctx.save();
        ctx.translate(b.x, b.y);
        ctx.scale(b.dir, 1);
        ctx.fillStyle = C.paleWhite;
        ctx.shadowColor = C.silkCyan;
        ctx.shadowBlur = 20;
        ctx.beginPath();
        ctx.moveTo(24, 0);
        ctx.quadraticCurveTo(4, -18, -28, -8);
        ctx.quadraticCurveTo(-16, 0, -28, 8);
        ctx.quadraticCurveTo(4, 18, 24, 0);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }
    }

    drawParticles(ctx, ps) {
      for (const p of ps.particles) {
        ctx.globalAlpha = Math.max(0, p.life / p.maxLife);
        ctx.fillStyle = p.color;
        ctx.fillRect(p.x - p.size * 0.5, p.y - p.size * 0.5, p.size, p.size);
      }
      ctx.globalAlpha = 1;

      for (const r of ps.rings) {
        ctx.save();
        ctx.globalAlpha = Math.max(0, r.life / r.maxLife);
        ctx.strokeStyle = r.color;
        ctx.lineWidth = 2.6;
        ctx.beginPath();
        ctx.arc(r.x, r.y, r.r, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
    }

    drawForegroundAtmosphere(ctx, W, H, ps, player, zone) {
      // 飘浮微尘孢子
      ctx.save();
      for (const m of ps.motes) {
        ctx.fillStyle = zone && zone.id === 'mycelium' ? '#6ee7b7' : '#bae6fd';
        ctx.globalAlpha = m.alpha;
        ctx.beginPath();
        ctx.arc(m.x, m.y, m.r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      // 深渊暗角 Vignette
      const vig = ctx.createRadialGradient(W * 0.5, H * 0.5, H * 0.34, W * 0.5, H * 0.5, W * 0.72);
      vig.addColorStop(0, 'rgba(0,0,0,0)');
      vig.addColorStop(1, player.hp === 1 ? 'rgba(90, 10, 22, 0.52)' : 'rgba(2, 4, 10, 0.58)');
      ctx.fillStyle = vig;
      ctx.fillRect(0, 0, W, H);

      if (player.hurtFlash > 0) {
        ctx.fillStyle = `rgba(244, 63, 94, ${player.hurtFlash * 0.38})`;
        ctx.fillRect(0, 0, W, H);
      }
    }

    drawHUD(ctx, W, H, world, dt) {
      const { player, level, enemies } = world;
      ctx.save();

      // --- 1) 左上角：灵魂容器球 + 苍白面具血条 ---
      const orbX = 56;
      const orbY = 56;
      const orbR = 30;
      const soulRatio = player.soul / Silkhollow.CFG.SOUL_MAX;
      const canCast = player.soul >= Silkhollow.CFG.SOUL_COST;

      // 球体底色
      ctx.fillStyle = 'rgba(8, 13, 25, 0.88)';
      ctx.beginPath();
      ctx.arc(orbX, orbY, orbR, 0, Math.PI * 2);
      ctx.fill();

      // 动态波浪灵魂液面
      ctx.save();
      ctx.beginPath();
      ctx.arc(orbX, orbY, orbR - 3, 0, Math.PI * 2);
      ctx.clip();
      const liquidY = orbY + orbR - soulRatio * (orbR * 2);
      ctx.fillStyle = canCast ? '#e0f2fe' : '#64748b';
      ctx.beginPath();
      ctx.moveTo(orbX - orbR, orbY + orbR);
      for (let x = -orbR; x <= orbR; x += 4) {
        const wy = liquidY + Math.sin(this.time * 4.5 + x * 0.14) * 3;
        ctx.lineTo(orbX + x, wy);
      }
      ctx.lineTo(orbX + orbR, orbY + orbR);
      ctx.closePath();
      ctx.fill();
      ctx.restore();

      // 容器金属外框 + 顶部双角饰纹
      ctx.strokeStyle = canCast ? C.silkBright : '#94a3b8';
      ctx.lineWidth = canCast ? 3 : 2.2;
      if (canCast) {
        ctx.shadowColor = C.silkCyan;
        ctx.shadowBlur = 12;
      }
      ctx.beginPath();
      ctx.arc(orbX, orbY, orbR, 0, Math.PI * 2);
      ctx.stroke();
      ctx.shadowBlur = 0;

      // 灵魂数字与快捷键小标
      ctx.fillStyle = '#0f172a';
      ctx.font = 'bold 11px Consolas, monospace';
      ctx.textAlign = 'center';
      if (soulRatio > 0.35) ctx.fillText(Math.floor(player.soul), orbX, orbY + 4);
      ctx.fillStyle = '#94a3b8';
      ctx.font = '10px "Microsoft YaHei", sans-serif';
      ctx.fillText('[F] 灵魂', orbX, orbY + 44);

      // 装饰衔接横梁
      ctx.strokeStyle = 'rgba(186, 230, 253, 0.55)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(orbX + orbR, orbY - 8);
      ctx.lineTo(orbX + orbR + player.maxHp * 32 + 12, orbY - 8);
      ctx.stroke();

      // 面具血格
      for (let i = 0; i < player.maxHp; i++) {
        const mx = orbX + orbR + 24 + i * 32;
        const my = orbY - 12;
        const filled = i < player.hp;
        ctx.save();
        ctx.translate(mx, my);
        ctx.fillStyle = filled ? C.paleWhite : 'rgba(15, 23, 42, 0.72)';
        ctx.strokeStyle = filled ? '#bae6fd' : '#475569';
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.moveTo(-9, -2);
        ctx.quadraticCurveTo(-10, -13, -5, -16);
        ctx.lineTo(0, -12);
        ctx.lineTo(5, -16);
        ctx.quadraticCurveTo(10, -13, 9, -2);
        ctx.quadraticCurveTo(0, 12, -9, -2);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
        if (filled) {
          ctx.fillStyle = '#070a14';
          ctx.beginPath();
          ctx.arc(-3.5, -2, 2, 0, Math.PI * 2);
          ctx.arc(3.5, -2, 2, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      }

      // 苍白微尘计数 + 能力徽章
      ctx.fillStyle = C.paleBlue;
      ctx.font = '13px Consolas, "Microsoft YaHei", sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(`◆ 苍白微尘: ${player.shards}`, orbX + orbR + 16, orbY + 18);

      let badgeX = orbX + orbR + 16;
      if (player.hasSilkWings) {
        ctx.fillStyle = 'rgba(94, 234, 212, 0.18)';
        ctx.strokeStyle = C.silkCyan;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(badgeX, orbY + 26, 98, 20, 4);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = C.silkBright;
        ctx.font = '11px "Microsoft YaHei", sans-serif';
        ctx.fillText('✦ 苍白丝翼', badgeX + 10, orbY + 40);
        badgeX += 106;
      }
      if (player.hookEmpowerTimer > 0) {
        ctx.fillStyle = 'rgba(56, 189, 248, 0.25)';
        ctx.strokeStyle = C.silkBright;
        ctx.beginPath();
        ctx.roundRect(badgeX, orbY + 26, 94, 20, 4);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 11px "Microsoft YaHei", sans-serif';
        ctx.fillText('⚡ 钩刃蓄能!', badgeX + 10, orbY + 40);
      }

      // --- 2) 右上角：迷雾探索小地图 ---
      this.drawMiniMap(ctx, W - 216, 16, 200, 92, level, player);

      // --- 3) 底部中央：Boss 战专属哥特血条 ---
      const boss = enemies.find((e) => e.isBoss && e.active && !e.dead);
      if (boss) {
        this.bossHpTrail = Silkhollow.lerp(this.bossHpTrail, boss.hp, Math.min(1, dt * 4));
        const bw = 540;
        const bh = 14;
        const bx = (W - bw) * 0.5;
        const by = H - 56;

        ctx.fillStyle = '#f8fafc';
        ctx.font = '15px "Microsoft YaHei", sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`${boss.name}  ${boss.phase === 2 ? '· 渊丝暴走' : ''}`, W * 0.5, by - 10);

        ctx.fillStyle = 'rgba(7, 10, 20, 0.85)';
        ctx.fillRect(bx - 3, by - 3, bw + 6, bh + 6);
        ctx.strokeStyle = boss.phase === 2 ? C.corruptRed : '#94a3b8';
        ctx.lineWidth = 1.6;
        ctx.strokeRect(bx - 3, by - 3, bw + 6, bh + 6);

        // 缓降残血底条
        ctx.fillStyle = 'rgba(253, 224, 71, 0.55)';
        ctx.fillRect(bx, by, bw * Math.max(0, this.bossHpTrail / boss.maxHp), bh);

        // 主血条
        const bGrad = ctx.createLinearGradient(bx, by, bx + bw, by);
        bGrad.addColorStop(0, '#be123c');
        bGrad.addColorStop(1, '#fb923c');
        ctx.fillStyle = bGrad;
        ctx.fillRect(bx, by, bw * Math.max(0, boss.hp / boss.maxHp), bh);
      }

      ctx.restore();
    }

    drawMiniMap(ctx, x, y, w, h, level, player) {
      ctx.save();
      ctx.fillStyle = 'rgba(6, 10, 20, 0.78)';
      ctx.strokeStyle = 'rgba(148, 210, 255, 0.32)';
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, 5);
      ctx.fill();
      ctx.stroke();

      const scaleX = (w - 12) / level.cols;
      const scaleY = (h - 12) / level.rows;
      const ox = x + 6;
      const oy = y + 6;

      // 仅绘制已探索区域开放空间
      for (const key of level.visited) {
        const vy = Math.floor(key / 1000);
        const vx = key % 1000;
        const tx = vx * 2;
        const ty = vy * 2;
        if (tx < level.cols && ty < level.rows && !level.isSolidTile(tx, ty)) {
          ctx.fillStyle = tx > 115 ? 'rgba(244, 63, 94, 0.42)' : tx > 76 ? 'rgba(167, 139, 250, 0.38)' : ty < 21 ? 'rgba(52, 211, 153, 0.38)' : 'rgba(94, 234, 212, 0.34)';
          ctx.fillRect(ox + tx * scaleX, oy + ty * scaleY, Math.max(2, scaleX * 2.2), Math.max(2, scaleY * 2.2));
        }
      }

      // 长椅标记
      for (const b of level.benches) {
        ctx.fillStyle = C.silkCyan;
        ctx.fillRect(ox + (b.x / TS) * scaleX - 2, oy + (b.y / TS) * scaleY - 2, 4, 4);
      }

      // 玩家闪亮点
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(ox + (player.cx / TS) * scaleX, oy + (player.cy / TS) * scaleY, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    drawFullMap(canvas, world) {
      const ctx = canvas.getContext('2d');
      const W = canvas.width;
      const H = canvas.height;
      const { level, player } = world;

      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = '#060a14';
      ctx.fillRect(0, 0, W, H);

      const pad = 28;
      const scaleX = (W - pad * 2) / level.cols;
      const scaleY = (H - pad * 2) / level.rows;

      // 绘制瓦片房间结构（未探索区域呈现淡轮廓，已探索清晰高亮）
      for (let ty = 0; ty < level.rows; ty++) {
        for (let tx = 0; tx < level.cols; tx++) {
          if (level.isSolidTile(tx, ty)) continue;
          const vKey = Math.floor(ty / 2) * 1000 + Math.floor(tx / 2);
          const seen = level.visited.has(vKey);
          if (!seen) continue;
          ctx.fillStyle = tx > 115 ? 'rgba(244, 63, 94, 0.36)' : tx > 76 ? 'rgba(167, 139, 250, 0.34)' : ty < 21 ? 'rgba(52, 211, 153, 0.34)' : 'rgba(56, 189, 248, 0.32)';
          ctx.fillRect(pad + tx * scaleX, pad + ty * scaleY, scaleX + 0.5, scaleY + 0.5);
        }
      }

      // 区域标签
      const labels = [
        { text: '沉寂祭坛', tx: 16, ty: 24 },
        { text: '断丝深涧', tx: 54, ty: 42 },
        { text: '荧光菌廊', tx: 58, ty: 4.5 },
        { text: '钟鸣遗迹', tx: 96, ty: 41.5 },
        { text: '织渊王座 (BOSS)', tx: 130, ty: 19.5 },
      ];
      ctx.font = '13px "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#cbd5e1';
      ctx.textAlign = 'center';
      for (const l of labels) {
        ctx.fillText(l.text, pad + l.tx * scaleX, pad + l.ty * scaleY);
      }

      // 关键兴趣点
      for (const b of level.benches) {
        ctx.fillStyle = '#5eead4';
        ctx.beginPath();
        ctx.arc(pad + (b.x / TS) * scaleX, pad + (b.y / TS) * scaleY, 5, 0, Math.PI * 2);
        ctx.fill();
      }
      for (const bell of level.bells) {
        ctx.fillStyle = bell.triggered ? '#5eead4' : '#fbbf24';
        ctx.beginPath();
        ctx.arc(pad + (bell.x / TS) * scaleX, pad + (bell.y / TS) * scaleY, 5, 0, Math.PI * 2);
        ctx.fill();
      }
      for (const p of level.pickups) {
        if (p.collected || p.type === 'shard') continue;
        ctx.fillStyle = '#c084fc';
        ctx.beginPath();
        ctx.arc(pad + (p.x / TS) * scaleX, pad + (p.y / TS) * scaleY, 5.5, 0, Math.PI * 2);
        ctx.fill();
      }

      // Boss 位置
      ctx.fillStyle = '#f43f5e';
      ctx.beginPath();
      ctx.arc(pad + 134 * scaleX, pad + 32 * scaleY, 7, 0, Math.PI * 2);
      ctx.fill();

      // 玩家当前位置
      ctx.fillStyle = '#ffffff';
      ctx.shadowColor = '#ffffff';
      ctx.shadowBlur = 10;
      ctx.beginPath();
      ctx.arc(pad + (player.cx / TS) * scaleX, pad + (player.cy / TS) * scaleY, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
    }
  }

  Silkhollow.ParticleSystem = ParticleSystem;
  Silkhollow.Renderer = Renderer;
})(window);
