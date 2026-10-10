const assert = require('node:assert/strict');
const {workflowStudentId:f} = require('./education-identity.cjs');
const b='http://127.0.0.1:4321';
assert.deepEqual(f(null,b+'/Student/Details/203',b),{id:'203',source:'observed-details-url'});
assert.equal(f('9',b+'/Student/Details/203',b).id,'9');
for(const u of ['http://evil.test/Student/Details/203',b+'/Student/Create',b+'/Student/Details/0',b+'/Student/Details/2?x=1',b+'/Student/Details/2#x'])
  assert.equal(f(null,u,b).id,null);
console.log('Observed identity boundaries passed');
