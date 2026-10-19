import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';
import {DASH_PAGES,PAGE_NAMES} from '../frontend/src/dashboard/model.js';
const root=path.resolve(import.meta.dirname,'..');
const base=process.env.PITLANE_TEST_URL||'http://127.0.0.1:8000',fixture=process.env.PITLANE_FIXTURE_URL||'http://127.0.0.1:8001';
const checks=[],errors=[],expected=[],external=[],started=Date.now();let permitExpected=false;
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
const context=await browser.newContext({viewport:{width:1440,height:1050},acceptDownloads:true});
const page=await context.newPage();page.setDefaultTimeout(25000);
page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')(permitExpected?expected:errors).push(m.text())});
await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.protocol.startsWith('http')&&![new URL(base).origin,new URL(fixture).origin].includes(u.origin)){external.push(u.href);return r.abort()}return r.continue()});
const check=(name,ok=true)=>{checks.push({name,passed:!!ok});if(!ok)throw new Error(name)};
const ready=async(id='connections')=>{await page.locator(`[data-dashboard-page="${id}"] .db-page-heading`).waitFor();await page.locator(`[data-dashboard-page="${id}"] .db-busy`).waitFor({state:'hidden'})};
const nav=async id=>{if(await page.getByRole('button',{name:'Open navigation',exact:true}).isVisible())await page.getByRole('button',{name:'Open navigation',exact:true}).click();await page.locator('.sidebar nav').getByRole('button',{name:PAGE_NAMES[id],exact:true}).click();await ready(id)};
const job=async(button,endpoint,ok=true)=>{
 const previous=await context.request.get(fixture+'/api/connections/status').then(r=>r.json());
 const finished=page.waitForResponse(async r=>{if(!r.url().endsWith('/api/connections/status')||r.request().method()!=='GET')return false;const d=await r.json();return !!d.job&&d.job.id!==previous.job?.id&&['succeeded','failed'].includes(d.job.state)});
 const response=page.waitForResponse(r=>r.url().includes('/api/connections/'+endpoint)&&r.request().method()==='POST');await button.click();const r=await response,j=await r.json();check(`Action accepted: ${endpoint}`,r.status()===202);
 const d=await (await finished).json();check(`Job result: ${endpoint}`,d.job.id===j.id&&d.job.state===(ok?'succeeded':'failed'));
 await page.waitForFunction(state=>document.querySelector('.db-connection-job')?.parentElement?.innerText.includes(state.toUpperCase()),d.job.state);await page.waitForTimeout(180);return d.job.result;
};
const shot=async name=>{await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));await page.waitForTimeout(80);await page.screenshot({path:path.join(root,'qa',name+'.png'),fullPage:true})};
try{
 const reset=await context.request.post(fixture+'/_qa/reset',{headers:{'X-Pitlane-Test-Token':'offline-fixture-only'}});if(!reset.ok())throw new Error('Start the dedicated offline fixture server before this suite.');
 await page.goto(base+'/#connections',{waitUntil:'networkidle'});await ready();
 check('Connections works before credentials or catalog access',await page.locator('h1').innerText()==='Your data. Your infrastructure.');
 check('Default readiness makes no false cloud claim',(await page.locator('main').innerText()).includes('No services contacted'));
 check('No provider key input exists',await page.locator('input').evaluateAll(els=>els.every(el=>!/(Elastic|Hopsworks).*key/i.test(el.getAttribute('aria-label')||''))));
 check('Unconfigured provider tests and writes are disabled',await page.getByRole('button',{name:'Test Elastic read access',exact:true}).isDisabled()&&await page.getByRole('button',{name:'Test Hopsworks access',exact:true}).isDisabled()&&await page.getByRole('button',{name:'Publish & verify batch',exact:true}).isDisabled());
 const download=page.waitForEvent('download');await page.getByRole('link',{name:'Setup guide',exact:true}).click();const file=await download;check('Credential setup guide is a working download',file.suggestedFilename()==='PITLANE-CLOUD-SETUP.md');
 await shot('25-connections-ready');
 await page.setViewportSize({width:390,height:844});check('Connections has no mobile document overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await shot('26-connections-mobile');
 await page.setViewportSize({width:1440,height:1050});await page.goto(fixture+'/#connections',{waitUntil:'networkidle'});await ready();
 check('Integration QA is visibly labeled as offline fixtures',(await page.locator('main').innerText()).includes('OFFLINE QA FIXTURE'));
 await page.getByRole('textbox',{name:'Operator token',exact:true}).fill('wrong');permitExpected=true;await page.getByRole('button',{name:'Unlock controls',exact:true}).click();await page.getByRole('alert').waitFor();check('Wrong operator token has a visible safe error',(await page.getByRole('alert').innerText()).includes('Incorrect operator token'));await page.waitForTimeout(150);permitExpected=false;
 await page.getByRole('textbox',{name:'Operator token',exact:true}).fill('operator_test_token_only_32_characters');await page.getByRole('button',{name:'Unlock controls',exact:true}).click();await page.getByText('OPERATOR SESSION ACTIVE',{exact:true}).waitFor();check('Operator session unlocks controls and clears token input',await page.getByRole('textbox',{name:'Operator token',exact:true}).count()===0);
 const storage=await page.evaluate(()=>JSON.stringify({...localStorage})+JSON.stringify({...sessionStorage})+document.cookie);check('Operator token is absent from browser storage and readable cookies',!storage.includes('operator_test_token_only_32_characters')&&!storage.includes('pitlane_operator'));
 await job(page.getByRole('button',{name:'Test Elastic read access',exact:true}),'test/elastic');check('Elastic readiness shows actual fixture counts',(await page.locator('.db-connection-indexes').innerText()).includes('1,426 records'));
 await job(page.getByRole('button',{name:'Test Hopsworks access',exact:true}),'test/hopsworks');
 await page.getByRole('combobox',{name:'Dashboard data provider',exact:true}).selectOption('elastic');await job(page.getByRole('button',{name:'Verify & activate modes',exact:true}),'modes');
 await nav('driver-standings');check('Actual Elastic-backed fixture values replace public standings',(await page.locator('.db-table tbody tr').first().innerText()).includes('27')&&!(await page.locator('.db-table tbody tr').first().innerText()).includes('295'));
 await nav('data');check('Native workbench replaces public-only coverage claims',(await page.locator('h1').innerText())==='Native data. Explicit supplements.');await page.getByRole('button',{name:'Preview records',exact:true}).click();await page.locator('.db-preview-meta').waitFor();check('Native schema preview contains source track status',(await page.locator('.db-code-block').last().innerText()).includes('"track_status": "1"'));
 await nav('connections');await page.getByRole('combobox',{name:'Pace feature provider',exact:true}).selectOption('hopsworks');await job(page.getByRole('button',{name:'Verify & activate modes',exact:true}),'modes',false);check('Missing feature group blocks activation without hiding the failure',(await page.locator('.db-connection-job').innerText()).includes('Publish'));
 await job(page.getByRole('button',{name:'Preview feature plan',exact:true}),'feature-plan');check('Real feature plan shows twenty rows from active Elastic source',(await page.locator('.db-connection-plan').innerText()).includes('20 computed rows')&&(await page.locator('.db-connection-plan').innerText()).includes('elastic source'));
 check('Publishing requires typed name confirmation',await page.getByRole('button',{name:'Publish & verify batch',exact:true}).isDisabled());await page.getByRole('textbox',{name:'Confirm feature group',exact:true}).fill('pitlane_testteam_race_pace');await job(page.getByRole('button',{name:'Publish & verify batch',exact:true}),'publish');check('Actual fixture write/read-back evidence appears',(await page.locator('.db-connection-verified').innerText()).includes('20 rows verified'));
 await job(page.getByRole('button',{name:'Verify & activate modes',exact:true}),'modes');
 await nav('race-pace');check('Race-pace UI actually declares Hopsworks read-back',(await page.locator('.db-metrics').innerText()).includes('Hopsworks'));check('Hybrid-source boundaries are visible',(await page.locator('main').innerText()).includes('Public supplements'));
 // Exercise every native-mode page; the fixture has one race and genuinely sparse season history.
 for(const id of DASH_PAGES){await nav(id);check(`Cloud-fixture route renders: ${PAGE_NAMES[id]}`,await page.locator('.db-load-error').count()===0&&await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
 await nav('timing');check('Timing remains a clearly labeled public reference',(await page.locator('main').innerText()).includes('Historical timing stays on the public'));
 await nav('connections');await page.getByRole('button',{name:'Read native lap',exact:true}).click();await page.getByText('12 NATIVE SAMPLES',{exact:true}).waitFor();check('Native telemetry is queried and plotted',await page.locator('.chart svg').count()>0);
 const nativeDownload=page.waitForEvent('download');await page.getByRole('button',{name:'Download native JSON',exact:true}).click();check('Bounded native telemetry export works',(await nativeDownload).suggestedFilename().includes('NOR-lap72'));
 await page.getByRole('spinbutton',{name:'Native telemetry lap',exact:true}).fill('99');await page.getByRole('button',{name:'Read native lap',exact:true}).click();await page.getByText('0 NATIVE SAMPLES',{exact:true}).waitFor();check('Empty native slice does not substitute a public replay',(await page.locator('main').innerText()).includes('No public telemetry has been substituted'));
 await page.getByRole('spinbutton',{name:'Native telemetry lap',exact:true}).fill('72');await page.getByRole('button',{name:'Read native lap',exact:true}).click();await page.getByText('12 NATIVE SAMPLES',{exact:true}).waitFor();await shot('27-connections-offline-fixture');
 await page.setViewportSize({width:390,height:844});check('Configured connection controls fit mobile',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 await page.getByRole('combobox',{name:'Dashboard data provider',exact:true}).selectOption('local');await page.getByRole('combobox',{name:'Pace feature provider',exact:true}).selectOption('local');await job(page.getByRole('button',{name:'Verify & activate modes',exact:true}),'modes');
 await page.getByRole('button',{name:'Lock session',exact:true}).click();await page.getByRole('button',{name:'Unlock controls',exact:true}).waitFor();check('Lock clears the operator session and disables actions',await page.getByRole('button',{name:'Test Elastic read access',exact:true}).isDisabled());
 check('No unexpected browser errors',errors.length===0);check('No external browser requests',external.length===0);
 console.log(`PASS ${checks.length} connection browser checks (offline fixtures; not live accounts)`);
}catch(e){await page.screenshot({path:path.join(root,'qa','connections-browser-failure.png'),fullPage:true});throw e}
finally{fs.writeFileSync(path.join(root,'qa','connections-browser-results.json'),JSON.stringify({created_at:new Date().toISOString(),scope:'Local readiness + in-memory Elastic HTTP / Hopsworks SDK fixtures. No live provider accounts.',duration_ms:Date.now()-started,passed:checks.filter(x=>x.passed).length,total:checks.length,checks,errors,expected,external},null,2));await browser.close()}
