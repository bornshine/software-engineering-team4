(function (global) {
  'use strict';

  const Silkhollow = (global.Silkhollow = global.Silkhollow || {});
  const TILE = Silkhollow.TILE;
  const TS = Silkhollow.TILE_SIZE;

  class Level {
    constructor() {
      this.cols = 148;
      this.rows = 44;
      this.width = this.cols * TS;
      this.height = this.rows * TS;
      this.grid = [];

      // 动态交互实体
      this.anchors = [];   // 渊丝环锚点
      this.bells = [];     // 共鸣丝铃
      this.gates = [];     // 可开启石闸门 / Boss 封印
      this.benches = [];   // 长椅存档点
      this.pickups = [];   // 遗物 / 面具碎片 / 苍白微尘
      this.tablets = [];   // 碎片化世界观与教学石碑
      this.decor = [];     // 场景装饰（发光晶簇、荧光蘑菇、吊链、石柱）
      this.enemySpawns = [];
      this.zoneRects = [];

      // 探索迷雾记录（按 2x2 瓦片块记录是否已探索）
      this.visited = new Set();

      this.buildWorld();
    }

    initSolid(tileType) {
      this.grid = [];
      for (let y = 0; y < this.rows; y++) {
        const row = new Uint8Array(this.cols);
        row.fill(tileType);
        this.grid.push(row);
      }
    }

    fillRect(x1, y1, x2, y2, tileType) {
      for (let y = Math.max(0, y1); y <= Math.min(this.rows - 1, y2); y++) {
        for (let x = Math.max(0, x1); x <= Math.min(this.cols - 1, x2); x++) {
          this.grid[y][x] = tileType;
        }
      }
    }

    carveRect(x1, y1, x2, y2) {
      this.fillRect(x1, y1, x2, y2, TILE.EMPTY);
    }

    paintBorderMaterial(x1, y1, x2, y2, tileType) {
      for (let y = Math.max(0, y1); y <= Math.min(this.rows - 1, y2); y++) {
        for (let x = Math.max(0, x1); x <= Math.min(this.cols - 1, x2); x++) {
          if (this.grid[y][x] === TILE.STONE) {
            this.grid[y][x] = tileType;
          }
        }
      }
    }

    addAnchor(id, tx, ty, active = true, bossPhase2 = false) {
      this.anchors.push({
        id,
        x: tx * TS,
        y: ty * TS,
        active,
        bossPhase2,
        pulse: Math.random() * Math.PI * 2,
      });
    }

    addBell(id, tx, ty, gateId, message) {
      this.bells.push({
        id,
        x: tx * TS,
        y: ty * TS,
        gateId,
        message,
        triggered: false,
        ringAnim: 0,
      });
    }

    addGate(id, tx, tyStart, tyEnd, label) {
      this.gates.push({
        id,
        tx,
        tyStart,
        tyEnd,
        x: tx * TS,
        y: tyStart * TS,
        w: TS,
        h: (tyEnd - tyStart + 1) * TS,
        open: false,
        openProgress: 0,
        label,
      });
    }

    addBench(id, tx, floorTy, name) {
      this.benches.push({
        id,
        x: tx * TS,
        y: floorTy * TS,
        name,
        lit: id === 'bench_sanctuary',
      });
    }

    addPickup(id, type, tx, ty, title, desc) {
      this.pickups.push({
        id,
        type, // 'silk_wings' | 'mask_shard' | 'shard'
        x: tx * TS,
        y: ty * TS,
        collected: false,
        title: title || '',
        desc: desc || '',
        bob: Math.random() * Math.PI * 2,
      });
    }

    addTablet(id, tx, floorTy, title, text) {
      this.tablets.push({
        id,
        x: tx * TS,
        y: floorTy * TS,
        title,
        text,
      });
    }

    buildWorld() {
      this.initSolid(TILE.STONE);

      // 生态分区定义（用于区域标题提示、背景雾效色调与大地图）
      this.zoneRects = [
        { id: 'sanctuary', x1: 0, y1: 23, x2: 32, y2: 43 },
        { id: 'chasm', x1: 32, y1: 21, x2: 76, y2: 43 },
        { id: 'mycelium', x1: 33, y1: 0, x2: 85, y2: 21 },
        { id: 'ruins', x1: 76, y1: 18, x2: 115, y2: 43 },
        { id: 'throne', x1: 115, y1: 18, x2: 147, y2: 43 },
      ];

      // =====================================================
      // 区域 1：沉寂祭坛 (Silent Sanctuary) tx: 2..31, ty: 26..38
      // =====================================================
      this.carveRect(3, 26, 30, 38);
      // 左侧圣坛装饰台阶
      this.fillRect(3, 37, 5, 38, TILE.TEMPLE);
      // 教学缓坡低平台与上方回环廊道
      this.fillRect(14, 37, 17, 37, TILE.PLATFORM);
      this.fillRect(19, 35, 22, 35, TILE.PLATFORM);
      // 祭坛上方捷径平台（连接捷径门 #1）
      this.fillRect(23, 31, 30, 31, TILE.PLATFORM);
      this.fillRect(15, 32, 20, 32, TILE.PLATFORM);

      // 通往区域 2 主通道
      this.carveRect(30, 34, 34, 38);
      // 来自区域 2 的上方捷径通道（由闸门 #1 封锁）
      this.carveRect(29, 27, 34, 30);

      // 祭坛实体
      this.spawnPos = { x: 7.5 * TS, y: 37.8 * TS };
      this.addBench('bench_sanctuary', 8.5, 39, '沉寂祭坛长椅');
      this.addTablet(
        'tab_1', 12.2, 39,
        '古窟残碑 · 骨钉与身法',
        'A / D 移动 · Space 跳跃与蹬墙跳 · 左键 / J 挥砍骨钉（空中按 S + 挥砍可下劈弹反） · Shift 幽影冲刺。'
      );
      this.addTablet(
        'tab_2', 20.5, 39,
        '渊丝秘刻 · 双模钩锁',
        '右键 / E / K 射出渊丝锁定发光丝环：短按极速拉拽弹射，长按进入物理摆荡，摆荡中按 Space 弹弓飞跃！'
      );
      this.addAnchor('a_sanc_1', 24.5, 33.0, true);
      this.addPickup('shard_s1', 'shard', 17.5, 31.0);
      this.addPickup('shard_s2', 'shard', 25.5, 30.0);
      this.enemySpawns.push({ type: 'crawler', x: 26 * TS, y: 38 * TS, minX: 22 * TS, maxX: 30 * TS });

      // =====================================================
      // 区域 2：断丝深涧 (Severed Chasm) tx: 33..74, ty: 23..40
      // =====================================================
      this.carveRect(33, 23, 74, 40);
      // 左侧安全起跳台
      this.fillRect(32, 39, 39, 41, TILE.STONE);
      // 左侧上方捷径阳台（可由此开启回祭坛的捷径门）
      this.fillRect(32, 31, 37, 31, TILE.STONE);
      // 中央休息石柱岛
      this.fillRect(51, 36, 56, 41, TILE.STONE);
      // 右侧着陆平台
      this.fillRect(67, 36, 75, 41, TILE.STONE);
      // 深渊底部的尖刺阵（失足回安全点，高手也可下劈弹跳！）
      this.fillRect(40, 40, 50, 40, TILE.SPIKE_UP);
      this.fillRect(57, 40, 66, 40, TILE.SPIKE_UP);

      // 向上通往区域 3（荧光菌廊）的攀爬平台与井道
      this.carveRect(49, 19, 57, 24);
      this.fillRect(48, 30, 51, 30, TILE.PLATFORM);
      this.fillRect(55, 27, 58, 27, TILE.PLATFORM);
      this.fillRect(49, 23, 52, 23, TILE.PLATFORM);

      // 通往区域 4（钟鸣遗迹）的右侧廊道
      this.carveRect(74, 31, 79, 35);

      // 断丝深涧 6 枚核心渊丝环 + 上行环（支持全程不落地连环摆荡飞跃！）
      this.addAnchor('a_chasm_1', 43.2, 33.8, true);
      this.addAnchor('a_chasm_2', 48.2, 31.8, true);
      this.addAnchor('a_chasm_mid', 53.8, 30.8, true);
      this.addAnchor('a_chasm_3', 59.5, 32.5, true);
      this.addAnchor('a_chasm_4', 64.8, 31.2, true);
      this.addAnchor('a_chasm_up1', 39.2, 29.2, true);
      this.addAnchor('a_chasm_up2', 53.2, 25.0, true);

      // 共鸣丝铃 #1：拉开祭坛单向捷径门！
      this.addGate('gate_shortcut', 31, 27, 30, '祭坛捷径闸门');
      this.addBell('bell_shortcut', 35.2, 26.8, 'gate_shortcut', '共鸣丝铃响彻古窟 — 通往沉寂祭坛的捷径已开启！');

      this.addTablet(
        'tab_3', 36.8, 39,
        '断丝深涧 · 空中续航',
        '钩锁释放或下劈命中敌怪/尖刺时，都会立刻刷新空中冲刺与钩锁冷却。善用浮游幽灵作为空中跳板！'
      );

      this.addPickup('shard_c1', 'shard', 53.5, 34.8);
      this.addPickup('shard_c2', 'shard', 45.8, 30.0);
      this.addPickup('shard_c3', 'shard', 62.2, 29.2);

      // 区域 2 敌怪
      this.enemySpawns.push({ type: 'wisp', x: 46 * TS, y: 35.5 * TS });
      this.enemySpawns.push({ type: 'crawler', x: 52.5 * TS, y: 35 * TS, minX: 51.2 * TS, maxX: 55.6 * TS });
      this.enemySpawns.push({ type: 'wisp', x: 62 * TS, y: 35.2 * TS });
      this.enemySpawns.push({ type: 'hopper', x: 71 * TS, y: 35 * TS, minX: 67.5 * TS, maxX: 74.5 * TS });

      // =====================================================
      // 区域 3：荧光菌廊 (Luminous Mycelium) tx: 35..83, ty: 5..20
      // =====================================================
      this.carveRect(36, 6, 82, 19);
      // 左侧小斜坡与下望连通口（可回落深涧拉响共鸣铃 #1）
      this.carveRect(36, 19, 41, 24);
      this.fillRect(36, 20, 39, 20, TILE.PLATFORM);
      // 菌廊多层次平台与石台
      this.fillRect(42, 17, 47, 17, TILE.PLATFORM);
      this.fillRect(54, 17, 61, 17, TILE.PLATFORM);
      this.fillRect(65, 16, 70, 16, TILE.PLATFORM);
      this.fillRect(74, 17, 81, 17, TILE.PLATFORM);

      this.fillRect(37, 13, 42, 13, TILE.PLATFORM);
      this.fillRect(48, 13, 53, 13, TILE.PLATFORM);
      this.fillRect(61, 12, 66, 12, TILE.PLATFORM);

      // 顶层神龛高台（存放「苍白丝翼」遗物！）
      this.fillRect(72, 10, 82, 11, TILE.MOSS);
      // 下层危险尖刺带（增加高空钩锁趣味）
      this.fillRect(62, 19, 73, 19, TILE.SPIKE_UP);

      // 右侧高空竖井：从荧光菌廊直接坠入钟鸣遗迹上层！
      this.carveRect(79, 19, 82, 24);
      this.fillRect(79, 19, 82, 19, TILE.PLATFORM);

      // 把区域 3 岩壁染色为荧光苔岩
      this.paintBorderMaterial(33, 3, 85, 21, TILE.MOSS);

      // 荧光菌廊丝环
      this.addAnchor('a_myc_1', 45.2, 14.5, true);
      this.addAnchor('a_myc_2', 57.5, 13.5, true);
      this.addAnchor('a_myc_3', 68.5, 11.2, true);
      this.addAnchor('a_myc_4', 67.5, 16.0, true);
      this.addAnchor('a_myc_5', 52.5, 19.8, true);

      // 核心银河城遗物：「苍白丝翼」
      this.addPickup(
        'relic_silk_wings',
        'silk_wings',
        78.5,
        8.8,
        '获得遗物 · 苍白丝翼',
        '解锁「空中二段跳」，且「渊丝钩锁」最大射程大幅延伸！'
      );
      this.addPickup('shard_m1', 'shard', 39.5, 11.8);
      this.addPickup('shard_m2', 'shard', 50.5, 11.8);
      this.addPickup('shard_m3', 'shard', 63.5, 10.8);

      // 区域 3 敌怪
      this.enemySpawns.push({ type: 'wisp', x: 43 * TS, y: 11 * TS });
      this.enemySpawns.push({ type: 'hopper', x: 57 * TS, y: 16 * TS, minX: 54 * TS, maxX: 60.5 * TS });
      this.enemySpawns.push({ type: 'wisp', x: 68 * TS, y: 13.5 * TS });
      this.enemySpawns.push({ type: 'crawler', x: 45 * TS, y: 19 * TS, minX: 41.5 * TS, maxX: 48.5 * TS });

      // =====================================================
      // 区域 4：钟鸣遗迹 (Chime Ruins) tx: 78..113, ty: 20..39
      // =====================================================
      this.carveRect(78, 21, 113, 38);
      // 左侧入口地面与重甲守卫大厅
      this.fillRect(77, 36, 99, 40, TILE.TEMPLE);
      // 尖刺沟壑（考验冲刺/钩锁/下劈）
      this.fillRect(100, 38, 107, 38, TILE.SPIKE_UP);
      this.fillRect(100, 39, 107, 40, TILE.TEMPLE);
      // 右侧 Boss 战前长椅圣台
      this.fillRect(108, 36, 115, 40, TILE.TEMPLE);

      // 上层钟楼回廊（存放共鸣铃 #2 开启王座巨门）
      this.fillRect(85, 29, 98, 29, TILE.TEMPLE);
      this.fillRect(79, 32, 83, 32, TILE.PLATFORM);
      this.fillRect(99, 31, 102, 31, TILE.PLATFORM);

      // 右上角隐藏密室高台（存放 +1 面具碎片！）
      this.fillRect(104, 26, 113, 27, TILE.TEMPLE);
      this.fillRect(104, 25, 105, 25, TILE.SPIKE_UP); // 入口边缘小尖刺增加探索成就感

      // 区域 4 与区域 5 染成古神殿石砖
      this.paintBorderMaterial(76, 18, 147, 43, TILE.TEMPLE);

      // 钟鸣遗迹丝环
      this.addAnchor('a_ruins_1', 91.5, 31.8, true);
      this.addAnchor('a_ruins_2', 103.5, 32.8, true);
      this.addAnchor('a_ruins_3', 82.8, 26.8, true);
      this.addAnchor('a_ruins_4', 99.8, 25.2, true);

      // 共鸣丝铃 #2 & 王座巨门
      this.addGate('gate_throne', 114, 31, 35, '织渊王座巨门');
      this.addBell('bell_throne', 91.5, 24.5, 'gate_throne', '古钟长鸣 — 通往「织渊王座」的巨门已轰然洞开！');

      // 隐藏面具碎片（最大 HP 5 -> 6）
      this.addPickup(
        'mask_shard_1',
        'mask_shard',
        110.5,
        24.6,
        '获得远古面具碎片',
        '苍白容器焕发微光：最大生命值永久 +1 并完全恢复！'
      );
      this.addPickup('shard_r1', 'shard', 88.0, 27.8);
      this.addPickup('shard_r2', 'shard', 108.5, 24.8);
      this.addPickup('shard_r3', 'shard', 103.5, 35.0);

      // 战前存档长椅 #2 与 Boss 战术碑文
      this.addBench('bench_ruins', 110.2, 36, '钟鸣遗迹长椅');
      this.addTablet(
        'tab_4', 112.2, 36,
        '织渊告诫 · 破核之丝',
        '前方即「残丝监守者 · 维洛斯」。当其重创跪地、胸口暴露青金丝核时，射出渊丝钩锁可触发毁灭处决！'
      );

      // 区域 4 敌怪
      this.enemySpawns.push({ type: 'knight', x: 92 * TS, y: 34.5 * TS, minX: 83 * TS, maxX: 98 * TS });
      this.enemySpawns.push({ type: 'knight', x: 93 * TS, y: 27.5 * TS, minX: 85.5 * TS, maxX: 97.5 * TS });
      this.enemySpawns.push({ type: 'wisp', x: 103.5 * TS, y: 29.5 * TS });
      this.enemySpawns.push({ type: 'hopper', x: 82 * TS, y: 35 * TS, minX: 78.5 * TS, maxX: 87 * TS });

      // =====================================================
      // 区域 5：织渊王座 (Throne of the Silk Weaver) tx: 116..144
      // =====================================================
      this.carveRect(114, 31, 117, 35); // 王座入口廊道
      this.carveRect(116, 21, 144, 35); // 宏伟 Boss 竞技场（地板 ty=36）
      this.fillRect(115, 36, 146, 40, TILE.TEMPLE);

      // Boss 战动态封印门（进入竞技场开战后自动落下，胜利或阵亡后解除）
      this.addGate('gate_boss_seal', 115, 31, 35, '渊丝封印');
      this.gates[this.gates.length - 1].open = true;
      this.gates[this.gates.length - 1].openProgress = 1;

      // 竞技场 3 枚战术高空丝环（中间常驻，左右在二阶段唤醒！）
      this.addAnchor('a_boss_mid', 130.0, 27.2, true, false);
      this.addAnchor('a_boss_left', 122.2, 28.0, false, true);
      this.addAnchor('a_boss_right', 137.8, 28.0, false, true);

      // Boss 出生配置
      this.bossArena = {
        triggerX: 119.5 * TS,
        minX: 116 * TS,
        maxX: 145 * TS,
        floorY: 36 * TS,
        ceilY: 21 * TS,
      };
      this.enemySpawns.push({
        type: 'boss',
        x: 136 * TS,
        y: 36 * TS - 84,
      });

      // 生成装饰物（钟乳石、荧光菌伞、晶簇、远古吊链、拱柱）
      this.populateDecor();
    }

    populateDecor() {
      // 扫描开放空间的顶与底，程序化安放氛围装饰（确定性伪随机，每次加载稳定美观）
      let seed = 1337;
      const rand = () => {
        seed = (seed * 16807) % 2147483647;
        return (seed - 1) / 2147483646;
      };

      for (let tx = 4; tx < this.cols - 3; tx += 2) {
        for (let ty = 6; ty < this.rows - 3; ty++) {
          if (this.grid[ty][tx] !== TILE.EMPTY) continue;

          // 贴顶：吊链或钟乳石
          if (this.isSolidTile(tx, ty - 1) && rand() < 0.24) {
            const kind = tx > 76 ? 'chain' : 'stalactite';
            this.decor.push({
              kind,
              x: tx * TS + TS * 0.5,
              y: ty * TS,
              len: 32 + rand() * 88,
              color: tx > 76 ? '#49527a' : '#1b263d',
            });
          }

          // 贴地：荧光蘑菇、晶簇或古石柱
          if (this.isSolidTile(tx, ty + 1) && rand() < 0.28) {
            const floorTile = this.grid[ty + 1][tx];
            if (floorTile === TILE.MOSS) {
              this.decor.push({
                kind: 'mushroom',
                x: tx * TS + rand() * TS,
                y: (ty + 1) * TS,
                size: 10 + rand() * 14,
                hue: rand() < 0.7 ? '#34d399' : '#38bdf8',
              });
            } else if (floorTile === TILE.TEMPLE && tx > 115 && tx % 4 === 0) {
              this.decor.push({
                kind: 'pillar',
                x: tx * TS + TS * 0.5,
                y: (ty + 1) * TS,
                h: 360 + rand() * 140,
              });
            } else if (rand() < 0.45) {
              this.decor.push({
                kind: 'crystal',
                x: tx * TS + rand() * TS,
                y: (ty + 1) * TS,
                size: 8 + rand() * 12,
                color: tx > 76 ? '#a78bfa' : '#5eead4',
              });
            }
          }
        }
      }
    }

    getTile(tx, ty) {
      if (tx < 0 || ty < 0 || tx >= this.cols || ty >= this.rows) return TILE.STONE;
      return this.grid[ty][tx];
    }

    isSolidTile(tx, ty) {
      const t = this.getTile(tx, ty);
      return t === TILE.STONE || t === TILE.MOSS || t === TILE.TEMPLE;
    }

    isSpikeTile(tx, ty) {
      const t = this.getTile(tx, ty);
      return t === TILE.SPIKE_UP || t === TILE.SPIKE_DOWN || t === TILE.SPIKE_LEFT || t === TILE.SPIKE_RIGHT;
    }

    boxTouchesSpikes(rect) {
      const minTx = Math.floor(rect.x / TS);
      const maxTx = Math.floor((rect.x + rect.w - 0.01) / TS);
      const minTy = Math.floor(rect.y / TS);
      const maxTy = Math.floor((rect.y + rect.h - 0.01) / TS);
      for (let ty = minTy; ty <= maxTy; ty++) {
        for (let tx = minTx; tx <= maxTx; tx++) {
          if (this.isSpikeTile(tx, ty)) {
            // 尖刺稍微内缩碰撞箱，提升操作公平度
            const sRect = { x: tx * TS + 4, y: ty * TS + 10, w: TS - 8, h: TS - 10 };
            if (Silkhollow.aabb(rect, sRect)) return true;
          }
        }
      }
      return false;
    }

    getClosedGateRects() {
      const res = [];
      for (const g of this.gates) {
        if (!g.open && g.openProgress < 0.8) {
          res.push({ x: g.x, y: g.y, w: g.w, h: g.h * (1 - g.openProgress) });
        }
      }
      return res;
    }

    setGateOpen(id, isOpen) {
      const g = this.gates.find((item) => item.id === id);
      if (g) g.open = isOpen;
    }

    hasLineOfSight(x1, y1, x2, y2) {
      const dist = Silkhollow.dist(x1, y1, x2, y2);
      const steps = Math.ceil(dist / 14);
      const closedGates = this.getClosedGateRects();
      for (let i = 1; i < steps; i++) {
        const t = i / steps;
        const x = x1 + (x2 - x1) * t;
        const y = y1 + (y2 - y1) * t;
        const tx = Math.floor(x / TS);
        const ty = Math.floor(y / TS);
        if (this.isSolidTile(tx, ty)) return false;
        for (const g of closedGates) {
          if (x >= g.x && x <= g.x + g.w && y >= g.y && y <= g.y + g.h) return false;
        }
      }
      return true;
    }

    triggerBell(bell, world) {
      bell.ringAnim = 1.0;
      world.audio.playBellChime();
      world.particles.ring(bell.x, bell.y, '#fde047', 110);
      world.particles.burst(bell.x, bell.y, 20, '#fef08a', 240);
      world.camera.shake(7, 0.25);

      if (!bell.triggered) {
        bell.triggered = true;
        this.setGateOpen(bell.gateId, true);
        world.showLore('共鸣丝铃', bell.message, 4.2);
      }
    }

    activateBossPhase2Anchors(world) {
      for (const a of this.anchors) {
        if (a.bossPhase2 && !a.active) {
          a.active = true;
          world.particles.ring(a.x, a.y, Silkhollow.COLORS.silkBright, 80);
          world.particles.burst(a.x, a.y, 18, Silkhollow.COLORS.silkCyan, 210);
        }
      }
    }

    resetBossArenaState() {
      this.setGateOpen('gate_boss_seal', true);
      for (const a of this.anchors) {
        if (a.bossPhase2) a.active = false;
      }
    }

    getZoneAt(px, py) {
      const tx = px / TS;
      const ty = py / TS;
      for (const zr of this.zoneRects) {
        if (tx >= zr.x1 && tx <= zr.x2 && ty >= zr.y1 && ty <= zr.y2) {
          return Silkhollow.ZONES.find((z) => z.id === zr.id) || Silkhollow.ZONES[0];
        }
      }
      return Silkhollow.ZONES[0];
    }

    markVisited(px, py) {
      const cx = Math.floor(px / (TS * 2));
      const cy = Math.floor(py / (TS * 2));
      for (let dy = -3; dy <= 3; dy++) {
        for (let dx = -4; dx <= 4; dx++) {
          const vx = cx + dx;
          const vy = cy + dy;
          if (vx >= 0 && vy >= 0 && vx < Math.ceil(this.cols / 2) && vy < Math.ceil(this.rows / 2)) {
            this.visited.add(vy * 1000 + vx);
          }
        }
      }
    }

    update(dt) {
      for (const a of this.anchors) {
        a.pulse += dt * 3.2;
      }
      for (const b of this.bells) {
        if (b.ringAnim > 0) b.ringAnim = Math.max(0, b.ringAnim - dt * 1.4);
      }
      for (const g of this.gates) {
        const target = g.open ? 1 : 0;
        g.openProgress = Silkhollow.lerp(g.openProgress, target, Math.min(1, dt * 4.5));
        if (Math.abs(g.openProgress - target) < 0.01) g.openProgress = target;
      }
      for (const p of this.pickups) {
        if (!p.collected) p.bob += dt * 3;
      }
    }
  }

  Silkhollow.Level = Level;
})(window);
