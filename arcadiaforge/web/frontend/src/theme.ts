import { createTheme } from '@mui/material/styles';

const ArcadiaColors = {
  ink: "#E6E6E6",
  dim: "#9AA4B2",
  forge: "#F59E0B",
  arc: "#22D3EE",
  steel: "#94A3B8",
  ok: "#22C55E",
  warn: "#FBBF24",
  err: "#EF4444",
  bg: "#121212",
  paper: "#1E1E1E",
};

export const theme = createTheme({
  palette: {
    mode: 'dark',
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
      default: ArcadiaColors.bg,
      paper: ArcadiaColors.paper,
    },
    text: {
      primary: ArcadiaColors.ink,
      secondary: ArcadiaColors.dim,
    },
  },
  typography: {
    fontFamily: '"JetBrains Mono", "Roboto Mono", monospace',
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
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
  },
});
