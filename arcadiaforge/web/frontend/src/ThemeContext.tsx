import React, { createContext, useContext, useState, useEffect, useMemo, type ReactNode } from 'react';
import { ThemeProvider as MuiThemeProvider, type PaletteMode } from '@mui/material';
import { createAppTheme, getThemeColors } from './theme';

// Storage key for persisted theme preference
const THEME_STORAGE_KEY = 'arcadiaforge-theme';

interface ThemeContextType {
  mode: PaletteMode;
  toggleTheme: () => void;
  setTheme: (mode: PaletteMode) => void;
  colors: ReturnType<typeof getThemeColors>;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

// Detect browser's color scheme preference
const getSystemTheme = (): PaletteMode => {
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return 'dark'; // Default fallback
};

// Get stored theme or fall back to system preference
const getInitialTheme = (): PaletteMode => {
  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'dark' || stored === 'light') {
      return stored;
    }
  }
  return getSystemTheme();
};

interface ThemeProviderProps {
  children: ReactNode;
}

export const ThemeContextProvider: React.FC<ThemeProviderProps> = ({ children }) => {
  const [mode, setMode] = useState<PaletteMode>(getInitialTheme);

  // Create theme object based on current mode
  const theme = useMemo(() => createAppTheme(mode), [mode]);
  const colors = useMemo(() => getThemeColors(mode), [mode]);

  // Listen for system theme changes
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

    const handleChange = (e: MediaQueryListEvent) => {
      // Only auto-switch if user hasn't set a manual preference
      const stored = localStorage.getItem(THEME_STORAGE_KEY);
      if (!stored) {
        setMode(e.matches ? 'dark' : 'light');
      }
    };

    // Modern browsers
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handleChange);
      return () => mediaQuery.removeEventListener('change', handleChange);
    }
    // Legacy browsers (Safari < 14)
    mediaQuery.addListener(handleChange);
    return () => mediaQuery.removeListener(handleChange);
  }, []);

  // Update CSS variables when theme changes
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-theme', mode);

    // Set CSS variables for scrollbar colors
    root.style.setProperty('--scrollbar-track', colors.scrollTrack);
    root.style.setProperty('--scrollbar-thumb', colors.scrollThumb);
    root.style.setProperty('--scrollbar-thumb-hover', colors.arc);
    root.style.setProperty('--bg-default', colors.bg);
  }, [mode, colors]);

  // Toggle between light and dark
  const toggleTheme = () => {
    setMode((prev) => {
      const newMode = prev === 'dark' ? 'light' : 'dark';
      localStorage.setItem(THEME_STORAGE_KEY, newMode);
      return newMode;
    });
  };

  // Set specific theme
  const setTheme = (newMode: PaletteMode) => {
    localStorage.setItem(THEME_STORAGE_KEY, newMode);
    setMode(newMode);
  };

  const contextValue: ThemeContextType = {
    mode,
    toggleTheme,
    setTheme,
    colors,
  };

  return (
    <ThemeContext.Provider value={contextValue}>
      <MuiThemeProvider theme={theme}>
        {children}
      </MuiThemeProvider>
    </ThemeContext.Provider>
  );
};

// Hook to access theme context
export const useTheme = (): ThemeContextType => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeContextProvider');
  }
  return context;
};

// Hook to just get the current mode
export const useThemeMode = (): PaletteMode => {
  const { mode } = useTheme();
  return mode;
};
