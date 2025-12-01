import asyncio
import os
from playwright.async_api import async_playwright

async def main():
    print("Lancement du navigateur...")
    async with async_playwright() as p:
        # Launch headed Chrome
        browser = await p.chromium.launch(headless=False)
        
        # Create context with viewport
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="fr-FR"
        )
        page = await context.new_page()
        
        print("Navigation vers Carrefour...")
        try:
            await page.goto("https://www.carrefour.fr/courses", timeout=60000)
        except Exception as e:
            print(f"Erreur navigation (pas grave si la page est la): {e}")
        
        print("\n" + "="*50)
        print("ACTION REQUISE :")
        print("1. Regardez la fenetre Chrome")
        print("2. Si il y a un challenge/captcha, resolvez-le")
        print("3. Attendez que la page d'accueil Carrefour soit chargee")
        print("4. Revenez ici et appuyez sur ENTREE")
        print("="*50 + "\n")
        
        input("Appuyez sur ENTREE pour sauvegarder les cookies...")
        
        # Ensure state directory exists
        os.makedirs("www/maxicourses_test/state", exist_ok=True)
        path = "www/maxicourses_test/state/carrefour_city.json"
        
        # Save state
        await context.storage_state(path=path)
        print(f"SUCCESS ! Cookies sauvegardes dans {path}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
