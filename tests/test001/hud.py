
__all__ = ["Attribute"]

class Attribute(object):
   def __init__(self, attr=""):
      super(Attribute, self).__init__()
      self.attr = attr

   def copy(self):
      return Attribute(self.attr)

   def value_to_string(self):
      return self.attr

   def string_to_value(self, s):
      self.attr = s

   # def __str__(self):
   #    return "Attribute('%s')" % self.attr

   def __repr__(self):
      return "Attribute('%s')" % self.attr

   def __eq__(self, oth):
      if isinstance(oth, Attribute):
         return self.attr == oth.attr
      return NotImplemented

   def __hash__(self):
      return hash(self.attr)

