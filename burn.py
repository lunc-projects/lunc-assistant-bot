"""Burn data — live, sourced. Correct endpoint only:
burn tax = /terra/tax/v1beta1/params -> burn_tax_rate (currently 0.015 = 1.5%)
NEVER use /terra/treasury/v1beta1/tax_rate (dead param, reads 0 wrongly).
80% of the tax is burned, 20% distributed — so effective burn = 1.2% of taxable flow.
"""
import httpx
LCD = "https://terra-classic-lcd.publicnode.com"
BURN_WALLET_NOTE = "Burns go to the burn module / dead burn address via the tax split."

async def get_burn_tax_rate() -> float | None:
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{LCD}/terra/tax/v1beta1/params"); r.raise_for_status()
            return float(r.json()["params"]["burn_tax_rate"])
    except Exception as e:
        print(f"burn rate fetch: {e}"); return None

async def get_lunc_supply() -> float | None:
    """Total LUNC supply in whole LUNC (uluna / 1e6). Supply drops are net of minting."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{LCD}/cosmos/bank/v1beta1/supply/by_denom?denom=uluna"); r.raise_for_status()
            amt = r.json()["amount"]["amount"]
            return int(amt) / 1e6
    except Exception as e:
        print(f"supply fetch: {e}"); return None

def burn_explainer(rate: float | None) -> str:
    if rate is None:
        return "🔥 LUNC Burn Tax\nCouldn't fetch the live rate right now.\nSource: PublicNode LCD /terra/tax/v1beta1/params"
    eff = rate * 0.8
    return (f"🔥 *LUNC Burn Tax — live*\n"
            f"Total tax rate: {rate*100:.2f}%\n"
            f"Burned share: 80% → effective burn {eff*100:.2f}% of taxable flow\n"
            f"Other 20% goes to community / oracle pools.\n"
            f"Set by governance (rate 1.5% was set by proposal 12223).\n"
            f"Source: PublicNode LCD — burn_tax_rate")
