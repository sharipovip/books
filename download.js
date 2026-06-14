const puppeteer = require('puppeteer');
const fs = require('fs');
const https = require('https');
const http = require('http');

const BASE = 'https://marifat.tj';
const CATEGORY_URL = process.env.CATEGORY_URL || 'https://marifat.tj/books/адабиёти-мактабӣ';
const FOLDER_NAME = process.env.FOLDER_NAME || 'Адабиёти мактабӣ';
const OUTPUT_DIR = 'books/' + FOLDER_NAME;

fs.mkdirSync(OUTPUT_DIR, { recursive: true });

function downloadFile(url, filepath) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https') ? https : http;
    const file = fs.createWriteStream(filepath);
    client.get(url, (response) => {
      if (response.statusCode !== 200) {
        reject(new Error('Status ' + response.statusCode));
        return;
      }
      response.pipe(file);
      file.on('finish', () => {
        file.close();
        resolve();
      });
    }).on('error', (err) => {
      fs.unlink(filepath, () => {});
      reject(err);
    });
  });
}

async function main() {
  console.log('Starting browser...');
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const page = await browser.newPage();
  page.setDefaultTimeout(30000);

  console.log('Going to: ' + CATEGORY_URL);
  await page.goto(CATEGORY_URL, { waitUntil: 'networkidle2', timeout: 60000 });

  await new Promise(r => setTimeout(r, 3000));

  const bookLinks = await page.evaluate((base) => {
    const links = [];
    document.querySelectorAll('a[href*="book/details"]').forEach(a => {
      let href = a.getAttribute('href');
      if (href && !href.startsWith('http')) href = base + href;
      if (href) links.push(href);
    });
    return [...new Set(links)];
  }, BASE);

  console.log('Found ' + bookLinks.length + ' books');

  for (let i = 0; i < bookLinks.length; i++) {
    const bookUrl = bookLinks[i];
    console.log('\n[' + (i+1) + '/' + bookLinks.length + '] Processing: ' + bookUrl);

    const bookPage = await browser.newPage();

    try {
      await bookPage.goto(bookUrl, { waitUntil: 'networkidle2', timeout: 60000 });
      await new Promise(r => setTimeout(r, 2000));

      const pdfInfo = await bookPage.evaluate(() => {
        const selectors = [
          'a[href*="admin/booksfiles"]',
          'a[href$=".pdf"]',
          'button[data-pdf]',
          '[onclick*="booksfiles"]',
          'iframe[src*="booksfiles"]',
          'iframe[src$=".pdf"]'
        ];

        for (const sel of selectors) {
          const el = document.querySelector(sel);
          if (el) {
            let url = el.href || el.getAttribute('data-pdf') || el.getAttribute('src');
            let title = document.querySelector('h1')?.textContent?.trim() || document.title;
            return { url, title };
          }
        }
        return null;
      });

      if (pdfInfo && pdfInfo.url) {
        let pdfUrl = pdfInfo.url;
        if (!pdfUrl.startsWith('http')) pdfUrl = BASE + pdfUrl;

        const safeTitle = (pdfInfo.title || 'book_' + (i+1))
          .replace(/[^a-zA-Z0-9А-Яа-яЁёҒғӢӣҚқӮӯҲҳҶҷ ]/g, '_')
          .replace(/\s+/g, '_')
          .substring(0, 80);

        const filename = OUTPUT_DIR + '/' + safeTitle + '.pdf';
        console.log('  PDF: ' + pdfUrl);
        console.log('  Saving: ' + filename);

        await downloadFile(pdfUrl, filename);
        console.log('  Downloaded');
      } else {
        console.log('  No PDF found');
      }

    } catch (err) {
      console.log('  Error: ' + err.message);
    }

    await bookPage.close();
    await new Promise(r => setTimeout(r, 1500));
  }

  await browser.close();
  console.log('\nDone!');
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
