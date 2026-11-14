/* 头像上传：校验类型与大小，裁成方形并缩到 512px，减少传输体积。 */
(function () {
  'use strict';

  var MAX_BYTES = 8 * 1024 * 1024;
  var SIZE = 512;
  var TYPES = /^image\/(png|jpeg|webp)$/;

  function read(file, done, fail) {
    if (!file) return;
    if (!TYPES.test(file.type)) { fail('type'); return; }
    if (file.size > MAX_BYTES) { fail('size'); return; }
    var reader = new FileReader();
    reader.onerror = function () { fail('read'); };
    reader.onload = function () {
      var img = new Image();
      img.onerror = function () { fail('image'); };
      img.onload = function () {
        var side = Math.min(img.width, img.height);
        var sx = (img.width - side) / 2;
        var sy = (img.height - side) / 2;
        var canvas = document.createElement('canvas');
        canvas.width = SIZE;
        canvas.height = SIZE;
        var ctx = canvas.getContext('2d');
        ctx.drawImage(img, sx, sy, side, side, 0, 0, SIZE, SIZE);
        try {
          done(canvas.toDataURL('image/png'));
        } catch (e) {
          fail('image');
        }
      };
      img.src = String(reader.result || '');
    };
    reader.readAsDataURL(file);
  }

  window.NexusAvatar = { read: read };
})();
