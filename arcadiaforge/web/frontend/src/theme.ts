import { createTheme, type Theme, type PaletteMode } from '@mui/material/styles';

// Arcadia brand colors - consistent across themes
export const ArcadiaColors = {
  // Accent colors (same in both themes)
  arc: "#22D3EE",     // Cyan - primary accent
  forge: "#F59E0B",   // Amber - secondary accent
  ok: "#22C55E",      // Green - success
  warn: "#FBBF24",    // Amber - warning
  err: "#EF4444",     // Red - error
  steel: "#94A3B8",   // Slate - tertiary
};

// Dark theme specific colors
const darkColors = {
  ink: "#E6E6E6",     // Primary text
  dim: "#9AA4B2",     // Secondary text
  bg: "#121212",      // Background
  paper: "#1E1E1E",   // Card/paper background
  scrollTrack: "#1a1a1a",
  scrollThumb: "#333",
};

// Light theme specific colors
const lightColors = {
  ink: "#1A1A1A",     // Primary text
  dim: "#64748B",     // Secondary text
  bg: "#F8FAFC",      // Background
  paper: "#FFFFFF",   // Card/paper background
  scrollTrack: "#E2E8F0",
  scrollThumb: "#94A3B8",
};

// Shared component overrides
const getComponents = (mode: PaletteMode) => ({
  MuiButton: {
    styleOverrides: {
      root: {
        textTransform: 'none' as const,
        borderRadius: 4,
      },
    },
  },
  MuiPaper: {
    styleOverrides: {
      root: {
        backgroundImage: 'none',
      },
    },
  },
  MuiCard: {
    styleOverrides: {
      root: {
        boxShadow: mode === 'dark'
          ? '0 1px 3px 0 rgba(0, 0, 0, 0.3)'
          : '0 1px 3px 0 rgba(0, 0, 0, 0.1)',
      },
    },
  },
});

// Create theme based on mode
export const createAppTheme = (mode: PaletteMode): Theme => {
  const colors = mode === 'dark' ? darkColors : lightColors;

  return createTheme({
    palette: {
      mode,
      primary: {
        main: ArcadiaColors.arc,
      },
      secondary: {
        main: ArcadiaColors.forge,
      },
      success: {
        main: ArcadiaColors.ok,
      },
      warning: {
        main: ArcadiaColors.warn,
      },
      error: {
        main: ArcadiaColors.err,
      },
      background: {
        default: colors.bg,
        paper: colors.paper,
      },
      text: {
        primary: colors.ink,
        secondary: colors.dim,
      },
    },
    typography: {
      fontFamily: '"JetBrains Mono", "Roboto Mono", monospace',
    },
    components: getComponents(mode),
  });
};

// Export pre-built themes for convenience
export const darkTheme = createAppTheme('dark');
export const lightTheme = createAppTheme('light');

// Export color getters for components that need raw color values
export const getThemeColors = (mode: PaletteMode) => ({
  ...ArcadiaColors,
  ...(mode === 'dark' ? darkColors : lightColors),
});

// Legacy export for backward compatibility
export const theme = darkTheme;
