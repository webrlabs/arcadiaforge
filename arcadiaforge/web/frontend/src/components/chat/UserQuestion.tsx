import React, { useState } from 'react';
import { Box, Typography, Button, TextField, Avatar } from '@mui/material';
import { MessageCircleQuestion } from 'lucide-react';

interface UserQuestionProps {
  questionId: string;
  question: string;
  options?: string[];
  inputType: 'text' | 'choice' | 'confirm';
  onRespond: (questionId: string, response: string) => void;
  isAnswered: boolean;
  timestamp: string;
}

const UserQuestion: React.FC<UserQuestionProps> = ({
  questionId,
  question,
  options,
  inputType,
  onRespond,
  isAnswered,
  timestamp,
}) => {
  const [textInput, setTextInput] = useState('');

  const handleSubmit = (response: string) => {
    if (response.trim()) {
      onRespond(questionId, response);
    }
  };

  return (
    <Box
      sx={{
        display: 'flex',
        gap: 1.5,
        mb: 2,
        alignItems: 'flex-start',
      }}
    >
      {/* Agent Avatar */}
      <Avatar
        sx={{
          width: 32,
          height: 32,
          bgcolor: 'rgba(251, 191, 36, 0.15)',
          border: '1px solid rgba(251, 191, 36, 0.3)',
        }}
      >
        <MessageCircleQuestion size={18} color="#FBBF24" />
      </Avatar>

      {/* Question Bubble */}
      <Box sx={{ flex: 1, maxWidth: 'calc(100% - 48px)' }}>
        <Box
          sx={{
            bgcolor: 'rgba(251, 191, 36, 0.08)',
            borderRadius: 2,
            borderTopLeftRadius: 0,
            border: '1px solid rgba(251, 191, 36, 0.25)',
            p: 2,
          }}
        >
          {/* Question Label */}
          <Typography
            variant="caption"
            sx={{
              color: '#FBBF24',
              fontWeight: 'bold',
              display: 'block',
              mb: 1,
              fontSize: '0.65rem',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          >
            Question
          </Typography>

          {/* Question Text */}
          <Typography
            variant="body2"
            sx={{
              color: 'text.primary',
              mb: 2,
              lineHeight: 1.6,
            }}
          >
            {question}
          </Typography>

          {/* Response Options */}
          {!isAnswered && (
            <Box sx={{ mt: 1.5 }}>
              {inputType === 'choice' && options && (
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                  {options.map((option, index) => (
                    <Button
                      key={index}
                      variant="outlined"
                      size="small"
                      onClick={() => handleSubmit(option)}
                      sx={{
                        borderColor: 'rgba(251, 191, 36, 0.4)',
                        color: '#FBBF24',
                        textTransform: 'none',
                        fontSize: '0.8rem',
                        '&:hover': {
                          borderColor: '#FBBF24',
                          bgcolor: 'rgba(251, 191, 36, 0.1)',
                        },
                      }}
                    >
                      {option}
                    </Button>
                  ))}
                </Box>
              )}

              {inputType === 'confirm' && (
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Button
                    variant="contained"
                    size="small"
                    onClick={() => handleSubmit('yes')}
                    sx={{
                      bgcolor: '#22C55E',
                      color: 'white',
                      textTransform: 'none',
                      '&:hover': {
                        bgcolor: '#16A34A',
                      },
                    }}
                  >
                    Yes
                  </Button>
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() => handleSubmit('no')}
                    sx={{
                      borderColor: 'rgba(239, 68, 68, 0.5)',
                      color: '#EF4444',
                      textTransform: 'none',
                      '&:hover': {
                        borderColor: '#EF4444',
                        bgcolor: 'rgba(239, 68, 68, 0.1)',
                      },
                    }}
                  >
                    No
                  </Button>
                </Box>
              )}

              {inputType === 'text' && (
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <TextField
                    size="small"
                    fullWidth
                    placeholder="Type your response..."
                    value={textInput}
                    onChange={(e) => setTextInput(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && handleSubmit(textInput)}
                    sx={{
                      '& .MuiOutlinedInput-root': {
                        bgcolor: 'rgba(0, 0, 0, 0.2)',
                        '& fieldset': {
                          borderColor: 'rgba(251, 191, 36, 0.3)',
                        },
                        '&:hover fieldset': {
                          borderColor: 'rgba(251, 191, 36, 0.5)',
                        },
                        '&.Mui-focused fieldset': {
                          borderColor: '#FBBF24',
                        },
                      },
                      '& .MuiInputBase-input': {
                        fontSize: '0.85rem',
                      },
                    }}
                  />
                  <Button
                    variant="contained"
                    size="small"
                    onClick={() => handleSubmit(textInput)}
                    disabled={!textInput.trim()}
                    sx={{
                      bgcolor: '#FBBF24',
                      color: '#000',
                      fontWeight: 'bold',
                      '&:hover': {
                        bgcolor: '#F59E0B',
                      },
                      '&:disabled': {
                        bgcolor: 'rgba(251, 191, 36, 0.3)',
                        color: 'rgba(0, 0, 0, 0.5)',
                      },
                    }}
                  >
                    Send
                  </Button>
                </Box>
              )}
            </Box>
          )}

          {/* Answered State */}
          {isAnswered && (
            <Typography
              variant="caption"
              sx={{
                color: '#22C55E',
                fontStyle: 'italic',
                display: 'block',
                mt: 1,
              }}
            >
              Answered
            </Typography>
          )}
        </Box>

        {/* Timestamp */}
        <Typography
          variant="caption"
          sx={{
            color: 'text.secondary',
            fontSize: '0.65rem',
            mt: 0.5,
            display: 'block',
            opacity: 0.7,
          }}
        >
          {new Date(timestamp).toLocaleTimeString()}
        </Typography>
      </Box>
    </Box>
  );
};

export default UserQuestion;
