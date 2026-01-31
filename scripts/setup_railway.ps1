# Railway Setup Script for Voice Agent Platform (PowerShell)
# Run this after: railway login

$ErrorActionPreference = "Stop"

Write-Host "Setting up Railway project for Voice Agent Platform..." -ForegroundColor Cyan

# Navigate to project root
Set-Location (Split-Path -Parent $PSScriptRoot)

# Create new project
Write-Host "Creating Railway project..." -ForegroundColor Yellow
railway init --name voice-agent-platform

# Add PostgreSQL
Write-Host "Adding PostgreSQL database..." -ForegroundColor Yellow
railway add --plugin postgresql

# Add Redis
Write-Host "Adding Redis..." -ForegroundColor Yellow
railway add --plugin redis

# Generate secret key
$chars = "0123456789abcdef"
$secretKey = -join (1..64 | ForEach-Object { $chars[(Get-Random -Maximum $chars.Length)] })

# Set environment variables
Write-Host "Setting environment variables..." -ForegroundColor Yellow
railway variables set APP_NAME=voice-agent-platform
railway variables set APP_ENV=production
railway variables set DEBUG=false
railway variables set SECRET_KEY=$secretKey
railway variables set JWT_ALGORITHM=HS256
railway variables set JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
railway variables set JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
railway variables set VECTOR_STORE_TYPE=pgvector
railway variables set RATE_LIMIT_REQUESTS=100
railway variables set RATE_LIMIT_WINDOW_SECONDS=60

Write-Host ""
Write-Host "Railway project created!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Go to Railway dashboard: https://railway.app/dashboard"
Write-Host "2. Add these environment variables manually:"
Write-Host "   - LIVEKIT_URL"
Write-Host "   - LIVEKIT_API_KEY"
Write-Host "   - LIVEKIT_API_SECRET"
Write-Host "   - OPENAI_API_KEY"
Write-Host "   - DEEPGRAM_API_KEY"
Write-Host "   - ELEVENLABS_API_KEY"
Write-Host "   - ELEVENLABS_VOICE_ID"
Write-Host "   - TWILIO_ACCOUNT_SID"
Write-Host "   - TWILIO_AUTH_TOKEN"
Write-Host "   - TWILIO_PHONE_NUMBER"
Write-Host ""
Write-Host "3. Deploy with: railway up"
Write-Host ""
