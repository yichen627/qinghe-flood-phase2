/** 真实浏览器验收：导入、起报、签发、权限切换及移动端布局。 */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main(){
  const target=path.join(__dirname,'../artifacts/browser');await fs.mkdir(target,{recursive:true});
  const browser=await chromium.launch({headless:true,...(process.env.BROWSER_CHANNEL?{channel:process.env.BROWSER_CHANNEL}:{})});
  const page=await browser.newPage({viewport:{width:1512,height:1100},deviceScaleFactor:1});const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const base=process.env.WORKBENCH_URL || 'http://127.0.0.1:8000';
  const credential={forecaster:process.env.API_KEY||'qinghe-local-demo',reviewer:process.env.REVIEWER_API_KEY||'qinghe-reviewer-demo',admin:process.env.ADMIN_API_KEY||'qinghe-admin-demo'};
  async function connect(role){
    if(!await page.locator('#auth-dialog').isVisible())await page.locator('#account-button').click();
    await page.locator('#key-input').fill(credential[role]);await page.locator('#auth-form button[type=submit]').click();
    await page.waitForFunction(role=>document.querySelector('#role-label').textContent===role,{forecaster:'预报员',reviewer:'值班长',admin:'管理员'}[role]);
    await page.locator('#auth-dialog').waitFor({state:'hidden'});
    await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
  }
  async function submitAction(){await page.locator('#action-form button[type=submit]').click();await page.locator('#action-dialog').waitFor({state:'hidden'});}
  try{
    await page.goto(base);await connect('forecaster');
    await page.locator('#import-button').click();await page.locator('#sample-select').selectOption('event1');
    await page.waitForFunction(()=>document.querySelector('#state-input').value.includes('WU'));
    const state0=JSON.parse(await page.locator('#state-input').inputValue());assert('QI' in state0);
    await page.locator('#import-form button[type=submit]').click();await page.locator('#import-dialog').waitFor({state:'hidden'});
    const [queuedResponse]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/forecasts')&&r.request().method()==='POST'),page.locator('#run-button').click()]);
    const queued=await queuedResponse.json();assert.equal(queuedResponse.status(),202);
    await page.waitForFunction(id=>{const row=document.querySelector('#task-rows tr');return row?.querySelector('[data-task]')?.dataset.task===id&&row.classList.contains('selected')&&row.textContent.includes('计算完成');},queued.id,{timeout:60000});
    await page.waitForFunction(()=>document.querySelector('#chart svg')!==null);
    await page.waitForFunction(()=>document.querySelector('#dc-value').textContent!=='—');
    const dc=await page.locator('#dc-value').innerText();assert(Number(dc)>=.85);
    await page.locator('#toast').waitFor({state:'hidden'});await page.screenshot({path:path.join(target,'workbench-desktop.png'),fullPage:true,animations:'disabled'});
    const title='浏览器验收产品 '+Date.now();
    await page.locator('#draft-button').click();await page.locator('#product-title').fill(title);await submitAction();
    let row=page.locator('#product-rows tr').filter({hasText:title});await row.waitFor();assert(await row.locator('[data-product-action]').isDisabled());
    await connect('reviewer');
    for(const step of ['review','sign','publish']){
      row=page.locator('#product-rows tr').filter({hasText:title});await row.locator(`[data-product-action="${step}"]`).click();
      if(step==='review')await page.locator('#review-note').fill('过程线、峰值及冻结参数版本已核对');await submitAction();
    }
    assert.match(await row.innerText(),/已发布/);await page.screenshot({path:path.join(target,'products-desktop.png'),fullPage:true,animations:'disabled'});
    await page.locator('[data-view="audit"]').click();await page.locator('#audit-rows button').first().waitFor();
    await connect('admin');await page.locator('[data-view="schemes"]').click();await page.locator('#scheme-rows button').first().waitFor();
    assert.match(await page.locator('#scheme-rows').innerText(),/活动方案/);
    await page.locator('[data-view="operations"]').click();await page.locator('#schedule-rows tr').first().waitFor();
    await page.screenshot({path:path.join(target,'operations-desktop.png'),fullPage:true});
    await page.locator('[data-view="forecast"]').click();await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.waitForFunction(()=>Number(document.querySelector('#chart svg')?.getAttribute('viewBox').split(' ')[2])<400);
    await page.locator('#toast').waitFor({state:'hidden'});await page.screenshot({path:path.join(target,'workbench-mobile.png'),fullPage:true,animations:'disabled'});
    assert.deepEqual(errors,[]);
    const evidence={success:true,flows:['CSV与专属初态导入','真实起报与曲线','预报员禁止签发','值班长复核签发发布','方案活动状态','审计查询','调度与通知','390px无横向溢出'],forecast_id:queued.id,dc,console_errors:errors,product_title:title};
    await fs.writeFile(path.join(target,'acceptance.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence,null,2));
  }catch(error){await page.screenshot({path:path.join(target,'failure.png'),fullPage:true});throw error;}
  finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
