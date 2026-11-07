"""Fixed offline checks/build for a NEW owned static-site output contract."""

# Literal argv programs contain no generated input. The existing validation
# sandbox, immutable command receipt and archive verification remain mandatory.
CHECK = (
    "const fs=require('node:fs'),p=require('node:path');"
    "if(!fs.lstatSync('src').isDirectory())throw Error('src must be an ordinary directory');"
    "let count=0,size=0;"
    "function walk(dir){for(const name of fs.readdirSync(dir)){const f=p.join(dir,name),s=fs.lstatSync(f);"
    "if(s.isSymbolicLink())throw Error('Static source must not contain symlinks');"
    "if(s.isDirectory())walk(f);else{"
    "if(!s.isFile()||s.nlink!==1)throw Error('Static source requires ordinary unlinked files');"
    "if(++count>1000||(size+=s.size)>32*1024*1024)throw Error('Static source exceeds archive bounds');"
    "}}}walk('src');"
    "const entry=fs.readFileSync('src/index.html','utf8');"
    "if(!entry.trim())throw Error('Provide a nonempty src/index.html');"
)


def commands():
    return [
        {"kind": "test", "argv": ["node", "-e", CHECK]},
        {
            "kind": "build",
            "argv": [
                "node",
                "-e",
                CHECK + "fs.cpSync('src','dist',{recursive:true,force:false,errorOnExist:true});",
            ],
        },
    ]
