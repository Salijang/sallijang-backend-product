const sharp = require('sharp');
const { S3Client, GetObjectCommand, PutObjectCommand } = require('@aws-sdk/client-s3');

const s3 = new S3Client({ region: process.env.AWS_REGION || 'ap-northeast-2' });
const BUCKET = process.env.BUCKET_NAME;

exports.handler = async (event) => {
  for (const record of event.Records) {
    const key = decodeURIComponent(record.s3.object.key.replace(/\+/g, ' '));

    if (key.includes('/thumb/') || key.includes('/medium/')) continue;

    const filename = key.split('/').pop();
    const body = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: key }));
    const buffer = await streamToBuffer(body.Body);

    const [thumb, medium] = await Promise.all([
      sharp(buffer).resize(400, 400, { fit: 'cover' }).jpeg({ quality: 80 }).toBuffer(),
      sharp(buffer).resize(1000, null, { fit: 'inside', withoutEnlargement: true }).jpeg({ quality: 85 }).toBuffer(),
    ]);

    await Promise.all([
      s3.send(new PutObjectCommand({ Bucket: BUCKET, Key: `products/thumb/${filename}`, Body: thumb, ContentType: 'image/jpeg' })),
      s3.send(new PutObjectCommand({ Bucket: BUCKET, Key: `products/medium/${filename}`, Body: medium, ContentType: 'image/jpeg' })),
    ]);

    console.log(`[image-resize] ${key} → thumb(400x400) + medium(1000px) 생성 완료`);
  }
};

async function streamToBuffer(stream) {
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks);
}
