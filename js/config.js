// Public settings for cloud features. These values are safe to publish:
// access to data is protected by sign-in and row level security, not by these keys.
// Leave a value empty to turn that feature off.
export const config = {
  supabaseUrl: 'https://lfgolzddxnghacfeukml.supabase.co',
  supabaseKey:
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxmZ29semRkeG5naGFjZmV1a21sIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI4MzE4MzYsImV4cCI6MjEwODQwNzgzNn0.B79VIDS1mGPfZK8fLBajTQ3CxXIV4sfQNfTN6Gy8Sy4',
  // When the scheduled Claude check runs (UTC): every hour at `minute`, from fromHour to toHour.
  analysisSchedule: { minute: 1, fromHour: 6, toHour: 21 },
  googleClientId: '271009347599-sqgkegekmid7m8sqib0lojf57invjgr8.apps.googleusercontent.com',
};
