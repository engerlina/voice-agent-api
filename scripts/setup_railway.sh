#!/bin/bash
# Railway Setup Script for Voice Agent Platform
# Run this after: railway login

set -e

echo "🚂 Setting up Railway project for Voice Agent Platform..."

# Create new project
echo "📦 Creating Railway project..."
railway init --name voice-agent-platform

# Link to current directory
cd "$(dirname "$0")/.."

# Add PostgreSQL
echo "🐘 Adding PostgreSQL database..."
railway add --plugin postgresql

# Add Redis
echo "📦 Adding Redis..."
railway add --plugin redis

# Set environment variables
echo "⚙️ Setting environment variables..."
railway variables set APP_NAME=voice-agent-platform
railway variables set APP_ENV=production
railway variables set DEBUG=false
railway variables set SECRET_KEY=$(openssl rand -hex 32)

# JWT Settings
railway variables set JWT_ALGORITHM=HS256
railway variables set JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
railway variables set JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Vector store
railway variables set VECTOR_STORE_TYPE=pgvector

# Rate limiting
railway variables set RATE_LIMIT_REQUESTS=100
railway variables set RATE_LIMIT_WINDOW_SECONDS=60

echo ""
echo "✅ Railway project created!"
echo ""
echo "📝 Next steps:"
echo "1. Go to Railway dashboard: https://railway.app/dashboard"
echo "2. Add these environment variables manually:"
echo "   - LIVEKIT_URL"
echo "   - LIVEKIT_API_KEY"
echo "   - LIVEKIT_API_SECRET"
echo "   - OPENAI_API_KEY"
echo "   - DEEPGRAM_API_KEY"
echo "   - ELEVENLABS_API_KEY"
echo "   - ELEVENLABS_VOICE_ID"
echo "   - TWILIO_ACCOUNT_SID"
echo "   - TWILIO_AUTH_TOKEN"
echo "   - TWILIO_PHONE_NUMBER"
echo ""
echo "3. Deploy with: railway up"
echo ""
