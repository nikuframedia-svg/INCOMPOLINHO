// ═══════════════════════════════════════════════════════════
//  Ant Design Theme — Glassmorphism Industrial (Dark only)
//
//  Usage: <ConfigProvider theme={getIndustrialTheme('dark')}>
// ═══════════════════════════════════════════════════════════

import type { ThemeConfig } from 'antd';
import { theme } from 'antd';
import type { ThemeMode } from '@/stores/useUIStore';
import { PRIMARY } from './production-colors';

const sharedTokens = {
  fontFamily: "'Inter Variable', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  fontSize: 14,
  borderRadius: 8,
  borderRadiusLG: 12,
  borderRadiusSM: 6,
  padding: 16,
  paddingLG: 24,
  paddingSM: 12,
  paddingXS: 8,
  motionDurationMid: '0.2s',
  motionDurationSlow: '0.3s',
};

const sharedComponents = {
  Card: {
    headerBg: 'transparent',
    paddingLG: 20,
  },
  Button: {
    primaryColor: '#FFFFFF',
    fontWeight: 500,
  },
  Tag: {
    fontSizeSM: 11,
  },
  Badge: {
    fontSize: 12,
  },
  Tabs: {
    itemColor: undefined as string | undefined,
    itemActiveColor: PRIMARY.base,
    itemSelectedColor: PRIMARY.base,
    inkBarColor: PRIMARY.base,
  },
  Switch: {
    colorPrimary: PRIMARY.base,
    colorPrimaryHover: PRIMARY.hover,
  },
  Slider: {
    trackBg: PRIMARY.light,
    trackHoverBg: PRIMARY.light,
    handleColor: PRIMARY.base,
    handleActiveColor: PRIMARY.hover,
    railBg: undefined as string | undefined,
    railHoverBg: undefined as string | undefined,
  },
  Select: {
    optionSelectedBg: PRIMARY.light,
  },
  Input: {
    activeBorderColor: PRIMARY.base,
    hoverBorderColor: PRIMARY.hover,
  },
  Tooltip: {
    colorBgSpotlight: 'rgba(14, 16, 22, 0.95)',
    colorTextLightSolid: '#F0F0F2',
  },
};

export function getIndustrialTheme(mode: ThemeMode): ThemeConfig {
  if (mode === 'dark') {
    return {
      algorithm: theme.darkAlgorithm,
      token: {
        ...sharedTokens,
        colorPrimary: '#818CF8',
        colorBgBase: '#0E1016',
        colorBgContainer: 'transparent',
        colorBgElevated: '#0E1016',
        colorBgLayout: '#06080D',
        colorText: '#F0F0F2',
        colorTextSecondary: '#8E919A',
        colorTextTertiary: '#505362',
        colorBorder: 'rgba(255, 255, 255, 0.06)',
        colorBorderSecondary: 'rgba(255, 255, 255, 0.04)',
      },
      components: {
        ...sharedComponents,
        Table: {
          headerBg: 'rgba(255, 255, 255, 0.03)',
          headerColor: '#8E919A',
          cellPaddingBlock: 10,
          cellPaddingInline: 12,
          rowHoverBg: 'rgba(129, 140, 248, 0.06)',
          borderColor: 'rgba(255, 255, 255, 0.04)',
        },
        Tabs: {
          ...sharedComponents.Tabs,
          itemColor: '#8E919A',
        },
        Slider: {
          ...sharedComponents.Slider,
          railBg: 'rgba(255, 255, 255, 0.06)',
          railHoverBg: 'rgba(255, 255, 255, 0.08)',
        },
        Modal: {
          contentBg: '#0E1016',
          headerBg: '#0E1016',
          titleColor: '#F0F0F2',
        },
        Menu: {
          darkItemBg: 'transparent',
          darkSubMenuItemBg: 'transparent',
          darkItemSelectedBg: 'rgba(129, 140, 248, 0.12)',
          darkItemHoverBg: 'rgba(255, 255, 255, 0.04)',
        },
      },
    };
  }

  // Light mode (kept for compatibility, but app defaults to dark)
  return {
    algorithm: theme.defaultAlgorithm,
    token: {
      ...sharedTokens,
      colorPrimary: PRIMARY.base,
      colorBgBase: '#FFFFFF',
      colorBgContainer: '#FFFFFF',
      colorBgElevated: '#FFFFFF',
      colorBgLayout: '#F5F5F5',
      colorText: '#111827',
      colorTextSecondary: '#4B5563',
      colorTextTertiary: '#9CA3AF',
      colorBorder: '#E5E7EB',
      colorBorderSecondary: '#F1F5F9',
    },
    components: {
      ...sharedComponents,
      Table: {
        headerBg: '#F1F5F9',
        headerColor: '#4B5563',
        cellPaddingBlock: 10,
        cellPaddingInline: 12,
        rowHoverBg: 'rgba(129, 140, 248, 0.04)',
        borderColor: '#E5E7EB',
      },
      Tabs: {
        ...sharedComponents.Tabs,
        itemColor: '#4B5563',
      },
      Slider: {
        ...sharedComponents.Slider,
        railBg: '#E5E7EB',
        railHoverBg: '#E5E7EB',
      },
    },
  };
}

/** @deprecated Use getIndustrialTheme('light') instead */
export const industrialTheme = getIndustrialTheme('light');
