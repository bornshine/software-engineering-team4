(function (global) {
  'use strict';

  const Silkhollow = (global.Silkhollow = global.Silkhollow || {});

  Silkhollow.TILE_SIZE = 40;
  Silkhollow.VIEW_W = 1280;
  Silkhollow.VIEW_H = 720;

  Silkhollow.TILE = {
    EMPTY: 0,
    STONE: 1,
    MOSS: 2,
    PLATFORM: 3, // 单向平台
    SPIKE_UP: 4,
    SPIKE_DOWN: 5,
    SPIKE_LEFT: 6,
    SPIKE_RIGHT: 7,
    TEMPLE: 8,   // 华丽神殿石砖
  };

  Silkhollow.CFG = {
    // 核心物理与手感（60Hz 固定步长）
    FIXED_DT: 1 / 60,
    GRAVITY: 1520,
    MAX_FALL_SPEED: 780,
    WALL_SLIDE_SPEED: 135,

    // 玩家移动
    PLAYER_W: 24,
    PLAYER_H: 42,
    MOVE_SPEED: 315,
    GROUND_ACCEL: 2900,
    GROUND_DECEL: 3500,
    AIR_ACCEL: 2050,
    AIR_DECEL: 1150,

    // 跳跃（土狼时间 + 输入缓冲 + 可变跳）
    JUMP_VEL: -605,
    JUMP_CUT_MULT: 0.48,
    DOUBLE_JUMP_VEL: -560,
    WALL_JUMP_VX: 365,
    WALL_JUMP_VY: -575,
    WALL_JUMP_LOCK: 0.11,
    COYOTE_TIME: 0.11,
    JUMP_BUFFER: 0.12,

    // 幽影冲刺
    DASH_SPEED: 740,
    DASH_DURATION: 0.155,
    DASH_COOLDOWN: 0.48,

    // 骨钉战斗与下劈弹反
    NAIL_DURATION: 0.145,
    NAIL_COOLDOWN: 0.26,
    NAIL_DAMAGE: 18,
    NAIL_RANGE: 68,
    NAIL_WIDTH: 46,
    POGO_VEL: -535,
    HOOK_EMPOWER_MULT: 1.55,
    HOOK_EMPOWER_TIME: 0.72,

    // 灵魂与凝聚回血
    START_MAX_HP: 5,
    SOUL_MAX: 99,
    SOUL_COST: 33,
    SOUL_GAIN_HIT: 12,
    SOUL_GAIN_HOOK_HIT: 18,
    FOCUS_DURATION: 0.85,
    SOUL_BOLT_DAMAGE: 32,
    SOUL_BOLT_SPEED: 780,
    INVULN_TIME: 1.15,

    // 渊丝钩锁（短按拉拽 / 长按摆荡 / 钩敌突进 / 钩铃开路）
    GRAPPLE_RANGE_BASE: 365,
    GRAPPLE_RANGE_UPGRADED: 455,
    GRAPPLE_SHOOT_SPEED: 2250,
    GRAPPLE_ZIP_SPEED: 900,
    GRAPPLE_COOLDOWN: 0.20,
    GRAPPLE_HOLD_THRESHOLD: 0.16,
    SWING_MIN_LEN: 64,
    SWING_PUMP_FORCE: 860,
    SWING_REEL_SPEED: 195,
    SWING_DAMPING: 0.9965,
    SWING_SLINGSHOT_VY: -555,
    SWING_SLINGSHOT_BOOST: 1.26,

    // 打击感顿帧（Hitstop）
    HITSTOP_NAIL: 0.045,
    HITSTOP_CRIT: 0.075,
    HITSTOP_HURT: 0.09,
    HITSTOP_EXEC: 0.125,
  };

  Silkhollow.COLORS = {
    bgDeep: '#060913',
    bgMid: '#0d1527',
    stoneDark: '#162036',
    stoneBase: '#202d49',
    stoneEdge: '#47628a',
    mossDark: '#122b2e',
    mossBase: '#1b4144',
    mossEdge: '#34d399',
    templeDark: '#1c1d33',
    templeBase: '#2a2c4a',
    templeEdge: '#8b93c9',
    paleWhite: '#f4f8ff',
    paleBlue: '#bae6fd',
    silkCyan: '#5eead4',
    silkBright: '#ccfbf1',
    silkBlue: '#38bdf8',
    corruptOrange: '#fb923c',
    corruptRed: '#f43f5e',
    corruptGold: '#fde047',
    relicViolet: '#c084fc',
  };

  Silkhollow.ZONES = [
    { id: 'sanctuary', name: '沉寂祭坛', sub: 'SILENT SANCTUARY', tint: '#162b44', fog: 'rgba(94, 234, 212, 0.05)' },
    { id: 'chasm', name: '断丝深涧', sub: 'SEVERED CHASM', tint: '#11223a', fog: 'rgba(56, 189, 248, 0.06)' },
    { id: 'mycelium', name: '荧光菌廊', sub: 'LUMINOUS MYCELIUM', tint: '#0f2d2c', fog: 'rgba(52, 211, 153, 0.07)' },
    { id: 'ruins', name: '钟鸣遗迹', sub: 'CHIME RUINS', tint: '#1f1d38', fog: 'rgba(167, 139, 250, 0.06)' },
    { id: 'throne', name: '织渊王座', sub: 'THRONE OF THE WEAVER', tint: '#281322', fog: 'rgba(244, 63, 94, 0.07)' },
  ];

  Silkhollow.clamp = function (v, min, max) {
    return v < min ? min : v > max ? max : v;
  };

  Silkhollow.lerp = function (a, b, t) {
    return a + (b - a) * t;
  };

  Silkhollow.dist = function (x1, y1, x2, y2) {
    return Math.hypot(x2 - x1, y2 - y1);
  };

  Silkhollow.aabb = function (a, b) {
    return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  };
})(window);
