"""eSIM QR code viewer endpoints - public, no auth required."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.order import Order

router = APIRouter()


@router.get("/{order_number}", response_class=HTMLResponse)
async def view_esim_qr_code(
    order_number: str,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Public page to view and scan eSIM QR code.

    Used for SMS delivery - sends a short link that opens this page.
    No authentication required but only shows QR code, no sensitive data.
    """
    # Look up the order
    result = await db.execute(
        select(Order).where(Order.order_number == order_number)
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    if not order.esim_qr_code:
        # Show a "processing" page if QR code not yet available
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>eSIM Processing - Trvel</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, sans-serif;
            background: #fdfbf8;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{ max-width: 400px; text-align: center; }}
        .logo {{ color: #63BFBF; font-size: 32px; font-weight: 700; margin-bottom: 24px; }}
        .card {{ background: white; border-radius: 24px; padding: 40px; box-shadow: 0 4px 24px rgba(99, 191, 191, 0.15); }}
        .spinner {{
            width: 48px; height: 48px;
            border: 4px solid #e8f7f7;
            border-top-color: #63BFBF;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 24px;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        h2 {{ color: #010326; margin-bottom: 12px; font-size: 20px; }}
        p {{ color: #585b76; font-size: 15px; line-height: 1.6; }}
        .order-badge {{
            display: inline-block;
            background: #e8f7f7;
            border: 2px solid #63BFBF;
            color: #4fa9a9;
            padding: 8px 16px;
            border-radius: 100px;
            font-weight: 600;
            font-size: 13px;
            margin-top: 20px;
        }}
    </style>
    <meta http-equiv="refresh" content="5">
</head>
<body>
    <div class="container">
        <div class="logo">trvel</div>
        <div class="card">
            <div class="spinner"></div>
            <h2>Your eSIM is being prepared</h2>
            <p>This usually takes less than a minute. This page will refresh automatically.</p>
            <div class="order-badge">Order {order_number}</div>
        </div>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html, status_code=200)

    # Generate QR code URL using external API (same as website)
    qr_api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=280x280&data={quote(order.esim_qr_code)}"

    # Build Apple Universal Link for iOS 17.4+ direct install
    # Format: https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=LPA:1$SMDP$ACTIVATION_CODE
    apple_install_link = ""
    if order.esim_qr_code:
        # The QR code data is already in LPA format, use it directly
        apple_install_link = f"https://esimsetup.apple.com/esim_qrcode_provisioning?carddata={quote(order.esim_qr_code)}"

    # Get manual entry codes
    smdp_address = order.esim_smdp_address or ""
    activation_code = order.esim_matching_id or ""

    # Render the QR code page
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Your {order.destination_name} eSIM - Trvel</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, sans-serif;
            background: #fdfbf8;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 440px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 20px; }}
        .logo {{ color: #63BFBF; font-size: 28px; font-weight: 700; }}
        .card {{
            background: white;
            border-radius: 24px;
            padding: 32px 24px;
            box-shadow: 0 4px 24px rgba(99, 191, 191, 0.15);
        }}
        .success-banner {{
            background: linear-gradient(135deg, #63BFBF 0%, #75cfcf 100%);
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            margin-bottom: 24px;
        }}
        .success-banner h2 {{ color: white; font-size: 18px; margin-bottom: 4px; }}
        .success-banner p {{ color: rgba(255,255,255,0.9); font-size: 14px; }}
        .order-badge {{
            display: inline-block;
            background: #e8f7f7;
            border: 2px solid #63BFBF;
            color: #4fa9a9;
            padding: 8px 16px;
            border-radius: 100px;
            font-weight: 600;
            font-size: 13px;
            margin-bottom: 24px;
        }}
        .install-btn {{
            display: block;
            width: 100%;
            background: linear-gradient(135deg, #63BFBF 0%, #4fa9a9 100%);
            color: white;
            text-decoration: none;
            padding: 16px 24px;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            text-align: center;
            margin-bottom: 16px;
            box-shadow: 0 4px 12px rgba(99, 191, 191, 0.3);
        }}
        .install-btn:active {{ transform: scale(0.98); }}
        .install-note {{
            text-align: center;
            color: #585b76;
            font-size: 12px;
            margin-bottom: 24px;
        }}
        .divider {{
            display: flex;
            align-items: center;
            margin: 24px 0;
            color: #888a9d;
            font-size: 13px;
        }}
        .divider::before, .divider::after {{
            content: '';
            flex: 1;
            height: 1px;
            background: #F2E2CE;
        }}
        .divider span {{ padding: 0 16px; }}
        .qr-section {{
            background: #fdfbf8;
            border-radius: 16px;
            padding: 24px;
            text-align: center;
            margin-bottom: 24px;
        }}
        .qr-section h3 {{ font-size: 15px; color: #010326; margin-bottom: 16px; }}
        .qr-wrapper {{
            background: white;
            border-radius: 12px;
            padding: 16px;
            display: inline-block;
            border: 2px solid #F2E2CE;
        }}
        .qr-wrapper img {{ display: block; width: 200px; height: 200px; }}
        .qr-note {{ color: #585b76; font-size: 13px; margin-top: 16px; }}
        .manual-section {{
            background: #fdfbf8;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
        }}
        .manual-section h3 {{ font-size: 14px; color: #010326; margin-bottom: 16px; }}
        .code-block {{
            background: white;
            border: 1px solid #F2E2CE;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 12px;
        }}
        .code-label {{ font-size: 11px; color: #888a9d; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
        .code-value {{
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 12px;
            color: #010326;
            word-break: break-all;
            user-select: all;
            -webkit-user-select: all;
        }}
        .copy-hint {{ font-size: 11px; color: #63BFBF; margin-top: 8px; text-align: center; }}
        .instructions {{
            background: white;
            border: 2px solid #63BFBF;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
        }}
        .instructions h3 {{ font-size: 15px; color: #010326; margin-bottom: 16px; }}
        .device-section {{ margin-bottom: 16px; }}
        .device-section:last-child {{ margin-bottom: 0; }}
        .device-title {{ font-size: 14px; font-weight: 600; color: #010326; margin-bottom: 8px; }}
        .steps {{
            padding-left: 20px;
            color: #585b76;
            font-size: 13px;
            line-height: 1.8;
        }}
        .tips {{
            background: #e8f7f7;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 24px;
        }}
        .tips h4 {{ color: #4fa9a9; font-size: 14px; margin-bottom: 8px; }}
        .tips ul {{
            padding-left: 18px;
            color: #585b76;
            font-size: 13px;
            line-height: 1.7;
        }}
        .details {{
            background: #fdfbf8;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 20px;
        }}
        .detail-row {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #F2E2CE;
        }}
        .detail-row:last-child {{ border-bottom: none; }}
        .detail-label {{ color: #585b76; font-size: 14px; }}
        .detail-value {{ color: #010326; font-weight: 600; font-size: 14px; }}
        .support {{
            background: linear-gradient(135deg, #F2E2CE 0%, #f7efe4 100%);
            border-radius: 12px;
            padding: 16px;
            text-align: center;
        }}
        .support p {{ color: #585b76; font-size: 13px; }}
        .support a {{ color: #63BFBF; text-decoration: none; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">trvel</div>
        </div>

        <div class="card">
            <div class="success-banner">
                <h2>Your eSIM is ready! 🎉</h2>
                <p>Install it now on this device</p>
            </div>

            <div style="text-align: center;">
                <span class="order-badge">Order {order_number}</span>
            </div>

            <!-- One-tap Install Button (iOS 17.4+) -->
            <a href="{apple_install_link}" class="install-btn">
                 Tap to Install eSIM
            </a>
            <p class="install-note">Works on iPhone (iOS 17.4+) • Opens eSIM installer directly</p>

            <div class="divider"><span>or scan QR code</span></div>

            <div class="qr-section">
                <h3>📱 QR Code</h3>
                <div class="qr-wrapper">
                    <img src="{qr_api_url}" alt="eSIM QR Code">
                </div>
                <p class="qr-note">Scan from another device (laptop, tablet, second phone)</p>
            </div>

            <!-- Manual Entry Codes -->
            {f'''<div class="manual-section">
                <h3>⌨️ Manual Entry (all devices)</h3>
                <div class="code-block">
                    <div class="code-label">SM-DP+ Address</div>
                    <div class="code-value">{smdp_address}</div>
                </div>
                <div class="code-block">
                    <div class="code-label">Activation Code</div>
                    <div class="code-value">{activation_code}</div>
                </div>
                <p class="copy-hint">Tap and hold to copy</p>
            </div>''' if smdp_address and activation_code else ''}

            <div class="instructions">
                <h3>📲 How to Install Manually</h3>

                <div class="device-section">
                    <div class="device-title"> iPhone</div>
                    <ol class="steps">
                        <li>Settings → Mobile Data → Add eSIM</li>
                        <li>Tap <strong>"Enter Details Manually"</strong></li>
                        <li>Paste SM-DP+ Address and Activation Code</li>
                        <li>Tap "Add eSIM" when prompted</li>
                    </ol>
                </div>

                <div class="device-section">
                    <div class="device-title">🤖 Android</div>
                    <ol class="steps">
                        <li>Settings → Network & Internet → SIMs</li>
                        <li>Tap "Add eSIM" → <strong>"Enter manually"</strong></li>
                        <li>Enter SM-DP+ Address and Activation Code</li>
                        <li>Follow prompts to complete setup</li>
                    </ol>
                </div>
            </div>

            <div class="tips">
                <h4>💡 Pro Tips</h4>
                <ul>
                    <li><strong>Install now</strong> on WiFi before you travel</li>
                    <li><strong>Don't delete</strong> - eSIM can only be installed once</li>
                    <li><strong>When you land:</strong> Enable Data Roaming</li>
                </ul>
            </div>

            <div class="details">
                <div class="detail-row">
                    <span class="detail-label">Destination</span>
                    <span class="detail-value">🌏 {order.destination_name}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Plan</span>
                    <span class="detail-value">{order.plan_name} ({order.duration} days)</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Data</span>
                    <span class="detail-value" style="color: #63BFBF;">Unlimited</span>
                </div>
            </div>

            <div class="support">
                <p>Need help? <a href="mailto:support@trvel.co">support@trvel.co</a></p>
                <p>or call <a href="tel:+61340527555">+61 3 4052 7555</a></p>
            </div>
        </div>
    </div>
</body>
</html>"""

    return HTMLResponse(content=html, status_code=200)
