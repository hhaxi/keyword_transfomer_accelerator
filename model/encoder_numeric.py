"""Encoder extension contract. Q16 activations/parameters; unchanged v8 FFN.

Dense and QK use wide exact accumulation, RNE, then signed int32 saturation.
Softmax subtracts the row maximum and uses mathematical exp2 interpolation.
LayerNorm uses population variance, epsilon=4295*2^-32, integer sqrt and
one reciprocal per row. No evaluation-data-dependent numeric configuration.
"""
import math
import numpy as np
from ffn_numeric import ffn, rshift_even

EXP2_TABLE = np.array([round(2.0**(-i/256)*2**24) for i in range(257)],dtype=np.int64)


def sat32(x):
    return np.clip(x,-2**31,2**31-1).astype(np.int64)


def q16(x):
    raw=np.rint(np.asarray(x,dtype=np.float64)*65536)
    if not np.isfinite(raw).all() or np.any(raw < -2**31) or np.any(raw >= 2**31):
        raise ValueError('Q16 input/parameter overflow')
    return raw.astype(np.int64)


def dot(a,b,bias=None,shift=16):
    a=np.asarray(a,dtype=np.int64);b=np.asarray(b,dtype=np.int64)
    bound=int(np.max(np.abs(a)))*int(np.max(np.abs(b)))*a.shape[-1]
    if bias is not None:bound+=int(np.max(np.abs(bias)))*65536
    dtype=object if bound>=2**63 else np.int64
    z=a.astype(dtype)@b.astype(dtype)
    if bias is not None:z=z+np.asarray(bias,dtype=dtype)*65536
    if dtype is object:
        def round_one(v):
            m=abs(int(v));q,r=divmod(m,1<<shift)
            q+=r>(1<<(shift-1)) or (r==(1<<(shift-1)) and q&1)
            return min(2**31-1,max(-2**31,-q if v<0 else q))
        return np.frompyfunc(round_one,1,1)(z).astype(np.int64)
    return sat32(rshift_even(z,shift))


def exp_negative(d):
    d=np.asarray(d,dtype=np.int64)
    if np.any(d<0):raise ValueError('Expected nonnegative score difference')
    # log2(e) Q16 is fixed from mathematics, not fitted to samples.
    t=d*94548 >> 16
    idx=(t>>8)&255;frac=t&255
    e=EXP2_TABLE[idx]+((EXP2_TABLE[idx+1]-EXP2_TABLE[idx])*frac >> 8)
    return np.where(d>=16*65536,0,e>>np.minimum(t>>16,31))


def softmax(scores):
    scores=np.asarray(scores,dtype=np.int64)
    e=exp_negative(np.max(scores,axis=1,keepdims=True)-scores)
    den=np.sum(e,axis=1,keepdims=True)
    inv=(1<<48)//den
    return (e*inv)>>24


def layernorm(x,gamma,beta):
    x=np.asarray(x,dtype=np.int64);rows=[]
    if x.shape[-1]!=64:raise ValueError('LayerNorm dimension must be 64')
    for row in x:
        mean=sum(int(v) for v in row)>>6
        dx=sat32(row-mean)
        var=(sum(int(v)**2 for v in dx)>>6)+4295
        std=math.isqrt(var)
        inv=(1<<36)//std
        norm=(dx*inv)>>20
        rows.append(sat32(rshift_even(norm*np.asarray(gamma),16)+beta))
    return np.asarray(rows,dtype=np.int64)


def front(x,p):
    q=dot(x,p['wq']);k=dot(x,p['wk']);v=dot(x,p['wv'])
    score=dot(q,k.T,shift=19)
    prob=softmax(score)
    context=dot(prob,v,shift=24)
    a=dot(context,p['wo'],p['bo'])
    residual=sat32(x+a)
    z=layernorm(residual,p['g1'],p['n1'])
    return z,dict(q=q,k=k,v=v,score=score,prob=prob,context=context,attention=a,residual1=residual,z=z)


def tail(z,y,p,output_exponent):
    residual=sat32(z+rshift_even(y,-output_exponent-16))
    return layernorm(residual,p['g2'],p['n2']),residual


def encoder_layer(x,p,c1,c2):
    z,trace=front(x,p)
    xq=np.clip(rshift_even(z,16+c1['x_exponent']),-32768,32767)
    y,g,saturation=ffn(xq,p['w1'],p['b1'],p['w2'],p['b2'],c2['gelu_input_shift'],c2['gelu_output_shift'])
    out,residual=tail(z,y,p,c2['output_exponent'])
    trace.update(ffn_input=xq,ffn=y,gelu=g,residual2=residual,output=out,gelu_saturation=saturation)
    return out,trace
