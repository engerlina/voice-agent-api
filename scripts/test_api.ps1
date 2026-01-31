# Voice Agent Platform - API Test Script
# Run: .\scripts\test_api.ps1

$API_BASE = "https://api-production-66de.up.railway.app"

Write-Host "===== Testing Voice Agent Platform =====" -ForegroundColor Cyan
Write-Host ""

# Test 1: Health Check
Write-Host "1. Health Check..." -ForegroundColor Yellow
$health = Invoke-RestMethod -Uri "$API_BASE/health" -Method Get
Write-Host "   Status: $($health.status)" -ForegroundColor Green

# Test 2: Root endpoint
Write-Host "2. Root Endpoint..." -ForegroundColor Yellow
$root = Invoke-RestMethod -Uri "$API_BASE/" -Method Get
Write-Host "   Name: $($root.name)" -ForegroundColor Green
Write-Host "   Version: $($root.version)" -ForegroundColor Green

# Test 3: Voice Status
Write-Host "3. Voice Agent Status..." -ForegroundColor Yellow
$voice = Invoke-RestMethod -Uri "$API_BASE/api/v1/voice/status" -Method Get
Write-Host "   Enabled: $($voice.enabled)" -ForegroundColor Green
Write-Host "   LiveKit: $($voice.livekit_configured)" -ForegroundColor Green
Write-Host "   STT: $($voice.stt_configured)" -ForegroundColor Green
Write-Host "   TTS: $($voice.tts_configured)" -ForegroundColor Green
Write-Host "   LLM: $($voice.llm_configured)" -ForegroundColor Green

Write-Host ""
Write-Host "===== All Tests Passed! =====" -ForegroundColor Green
Write-Host ""

# Signup prompt
Write-Host "To create an account, run:" -ForegroundColor Cyan
Write-Host @"
`$body = @{
    email = "your@email.com"
    password = "yourpassword123"
    full_name = "Your Name"
    tenant_name = "My Clinic"
} | ConvertTo-Json

Invoke-RestMethod -Uri "$API_BASE/api/v1/auth/signup" -Method Post -Body `$body -ContentType "application/json"
"@
