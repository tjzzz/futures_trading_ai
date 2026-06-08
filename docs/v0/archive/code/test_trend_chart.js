// 趋势图功能测试脚本
// 用于验证实时探查页面趋势图是否正常工作

console.log('=== 趋势图功能测试 ===');

// 测试1：检查API端点
console.log('1. 测试API端点...');
fetch('/api/realtime/trend')
  .then(response => {
    console.log(`  状态: ${response.status} ${response.statusText}`);
    if (!response.ok) {
      throw new Error(`API请求失败: ${response.status}`);
    }
    return response.json();
  })
  .then(data => {
    console.log('  ✅ API响应正常');
    console.log(`  数据点数量: ${data.gold?.length || 0}`);
    console.log(`  时间范围: ${data.timeRange || '未知'}`);
    
    // 测试2：检查Chart.js库
    console.log('2. 检查Chart.js库...');
    if (typeof Chart !== 'undefined') {
      console.log('  ✅ Chart.js库已加载');
    } else {
      console.log('  ❌ Chart.js库未加载');
    }
    
    // 测试3：检查canvas元素
    console.log('3. 检查canvas元素...');
    const canvas = document.getElementById('trend-chart');
    if (canvas) {
      console.log(`  ✅ 找到canvas元素: ${canvas.id}`);
      console.log(`  尺寸: ${canvas.width}×${canvas.height}`);
    } else {
      console.log('  ❌ 未找到trend-chart canvas元素');
    }
    
    // 测试4：检查趋势图函数
    console.log('4. 检查趋势图函数...');
    if (typeof updateTrendChart === 'function') {
      console.log('  ✅ updateTrendChart函数存在');
    } else {
      console.log('  ❌ updateTrendChart函数不存在');
    }
    
    if (typeof drawTrendChart === 'function') {
      console.log('  ✅ drawTrendChart函数存在');
    } else {
      console.log('  ❌ drawTrendChart函数不存在');
    }
    
    // 测试5：手动触发趋势图更新
    console.log('5. 手动触发趋势图更新...');
    if (typeof updateTrendChart === 'function') {
      try {
        updateTrendChart('gold');
        console.log('  ✅ 趋势图更新已触发');
      } catch (error) {
        console.log('  ❌ 趋势图更新失败:', error.message);
      }
    }
    
    console.log('=== 测试完成 ===');
  })
  .catch(error => {
    console.error('测试失败:', error);
  });